"""AutoParts Pro: offline, transactional store operations. Python 3.11+."""
from __future__ import annotations
import csv, hashlib, hmac, io, json, os, secrets, sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get('AUTOPARTS_DATA', str(ROOT / 'data')))
DB = DATA / 'autoparts.sqlite3'

class BusinessError(Exception):
    pass

def now():
    return datetime.now().astimezone().isoformat(timespec='seconds')

def number(value, scale=100, name='Amount', positive=False):
    try:
        d = Decimal(str(value))
        if not d.is_finite() or d < 0 or d > Decimal('1000000000'):
            raise ValueError()
        if d * scale != (d * scale).to_integral_value():
            raise BusinessError(f'{name}: at most {2 if scale == 100 else 3} decimal places allowed.')
        n = int(d * scale)
        if positive and n <= 0:
            raise BusinessError(f'{name} must be greater than zero.')
        return n
    except (ValueError, InvalidOperation, TypeError):
        raise BusinessError(f'{name} must be a valid non-negative number.')

def rounded(n, denominator=1000):
    return int((Decimal(n) / denominator).quantize(Decimal('1'), rounding=ROUND_HALF_UP))

def text(value, limit=160, required=False):
    value = str(value or '').strip()
    if len(value) > limit or (required and not value):
        raise BusinessError(f'Enter a value between 1 and {limit} characters.' if required else f'Maximum {limit} characters.')
    return value

def password_hash(password, salt=None):
    if len(password) < 10 or len(password) > 200:
        raise BusinessError('Password must be 10–200 characters.')
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 260000).hex()
    return f'{salt}:{digest}'

def verify_password(password, stored):
    try:
        salt, digest = stored.split(':')
        test = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 260000).hex()
        return hmac.compare_digest(test, digest)
    except (ValueError, AttributeError):
        return False

class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc, tb):
        try:
            return super().__exit__(exc_type, exc, tb)
        finally:
            self.close()

def connect():
    DATA.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB, timeout=20, factory=ClosingConnection)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    c.execute('PRAGMA busy_timeout=20000')
    return c

@contextmanager
def transaction():
    c = connect()
    try:
        c.execute('BEGIN IMMEDIATE')
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()

def rows(c, sql, args=()):
    return [dict(r) for r in c.execute(sql, args)]

def audit(c, user, action, detail):
    c.execute('INSERT INTO audit(at,user_id,action,detail) VALUES(?,?,?,?)', (now(), user['id'] if user else None, action, json.dumps(detail, ensure_ascii=False)))

SCHEMA = '''
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,username TEXT UNIQUE COLLATE NOCASE NOT NULL,name TEXT NOT NULL,password TEXT NOT NULL,role TEXT NOT NULL CHECK(role IN ('admin','manager','cashier')),active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS products(id INTEGER PRIMARY KEY,barcode TEXT UNIQUE NOT NULL,name TEXT NOT NULL,category TEXT NOT NULL DEFAULT '',unit TEXT NOT NULL DEFAULT 'piece' CHECK(unit IN ('piece','kg','litre')),price INTEGER NOT NULL CHECK(price>=0),cost INTEGER NOT NULL CHECK(cost>=0),stock INTEGER NOT NULL DEFAULT 0 CHECK(stock>=0),minimum INTEGER NOT NULL DEFAULT 5000 CHECK(minimum>=0),active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS customers(id INTEGER PRIMARY KEY,name TEXT NOT NULL,phone TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS suppliers(id INTEGER PRIMARY KEY,name TEXT NOT NULL,phone TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS sales(id INTEGER PRIMARY KEY,request_id TEXT UNIQUE NOT NULL,at TEXT NOT NULL,user_id INTEGER NOT NULL REFERENCES users(id),customer_id INTEGER REFERENCES customers(id),subtotal INTEGER NOT NULL,discount INTEGER NOT NULL,tax INTEGER NOT NULL,total INTEGER NOT NULL,paid INTEGER NOT NULL,outstanding INTEGER NOT NULL CHECK(outstanding>=0),method TEXT NOT NULL,note TEXT NOT NULL DEFAULT '',store_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sale_items(id INTEGER PRIMARY KEY,sale_id INTEGER NOT NULL REFERENCES sales(id),product_id INTEGER NOT NULL REFERENCES products(id),name TEXT NOT NULL,barcode TEXT NOT NULL,unit TEXT NOT NULL,qty INTEGER NOT NULL,price INTEGER NOT NULL,cost INTEGER NOT NULL,line_total INTEGER NOT NULL,line_net INTEGER NOT NULL,returned INTEGER NOT NULL DEFAULT 0 CHECK(returned>=0 AND returned<=qty));
CREATE TABLE IF NOT EXISTS purchases(id INTEGER PRIMARY KEY,request_id TEXT UNIQUE NOT NULL,at TEXT NOT NULL,user_id INTEGER NOT NULL REFERENCES users(id),supplier_id INTEGER REFERENCES suppliers(id),reference TEXT NOT NULL,total INTEGER NOT NULL,paid INTEGER NOT NULL CHECK(paid>=0 AND paid<=total));
CREATE TABLE IF NOT EXISTS purchase_items(id INTEGER PRIMARY KEY,purchase_id INTEGER NOT NULL REFERENCES purchases(id),product_id INTEGER NOT NULL REFERENCES products(id),qty INTEGER NOT NULL,cost INTEGER NOT NULL,total INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS returns(id INTEGER PRIMARY KEY,request_id TEXT UNIQUE NOT NULL,at TEXT NOT NULL,user_id INTEGER NOT NULL REFERENCES users(id),sale_id INTEGER NOT NULL REFERENCES sales(id),total INTEGER NOT NULL,debt_reduction INTEGER NOT NULL,cash_refund INTEGER NOT NULL,tax_refund INTEGER NOT NULL DEFAULT 0,reason TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS return_items(id INTEGER PRIMARY KEY,return_id INTEGER NOT NULL REFERENCES returns(id),sale_item_id INTEGER NOT NULL REFERENCES sale_items(id),qty INTEGER NOT NULL,total INTEGER NOT NULL,cost_total INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS payments(id INTEGER PRIMARY KEY,request_id TEXT UNIQUE NOT NULL,at TEXT NOT NULL,user_id INTEGER NOT NULL REFERENCES users(id),sale_id INTEGER REFERENCES sales(id),purchase_id INTEGER REFERENCES purchases(id),amount INTEGER NOT NULL CHECK(amount>0),method TEXT NOT NULL,CHECK((sale_id IS NULL) != (purchase_id IS NULL)));
CREATE TABLE IF NOT EXISTS movements(id INTEGER PRIMARY KEY,at TEXT NOT NULL,user_id INTEGER REFERENCES users(id),product_id INTEGER NOT NULL REFERENCES products(id),qty INTEGER NOT NULL,kind TEXT NOT NULL,reference TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,at TEXT NOT NULL,user_id INTEGER REFERENCES users(id),action TEXT NOT NULL,detail TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_sales_at ON sales(at);
CREATE INDEX IF NOT EXISTS idx_sale_items_sale ON sale_items(sale_id);
CREATE INDEX IF NOT EXISTS idx_returns_sale ON returns(sale_id);
CREATE INDEX IF NOT EXISTS idx_movements_product ON movements(product_id);
'''

def initialize():
    with connect() as c:
        c.execute('PRAGMA journal_mode=WAL')
        c.executescript(SCHEMA)
        additions = {
            'customers': {k: "TEXT NOT NULL DEFAULT ''" for k in ('email','address','company','vehicle','registration','notes')},
            'products': {'part_number': "TEXT NOT NULL DEFAULT ''", 'oem_number': "TEXT NOT NULL DEFAULT ''", 'brand': "TEXT NOT NULL DEFAULT ''", 'condition': "TEXT NOT NULL DEFAULT 'aftermarket'", 'rack': "TEXT NOT NULL DEFAULT ''", 'warranty_days': 'INTEGER NOT NULL DEFAULT 0', 'fitments_json': "TEXT NOT NULL DEFAULT '[]'", 'origin_country': "TEXT NOT NULL DEFAULT ''", 'description': "TEXT NOT NULL DEFAULT ''"},
            'users': {'recovery_hash': "TEXT NOT NULL DEFAULT ''"},
            'sales': {'vehicle_id': 'INTEGER REFERENCES vehicles(id)', 'vehicle': "TEXT NOT NULL DEFAULT ''", 'registration': "TEXT NOT NULL DEFAULT ''"},
            'sale_items': {'part_json': "TEXT NOT NULL DEFAULT '{}'"},
        }
        for table, fields in additions.items():
            existing = {row[1] for row in c.execute(f'PRAGMA table_info({table})')}
            for column, definition in fields.items():
                if column not in existing: c.execute(f'ALTER TABLE {table} ADD COLUMN {column} {definition}')
        c.executescript(WARRANTY_SCHEMA)
        import workshop
        workshop.initialize(c)
        for k,v in {'store_name':'AutoParts Store','address':'','phone':'','receipt_footer':'Thank you for shopping with us!','tax_rate':'0','currency':'PKR','schema_version':'3'}.items():
            c.execute('INSERT OR IGNORE INTO settings VALUES(?,?)', (k,v))
        c.execute("UPDATE settings SET value='3' WHERE key='schema_version'")

def settings(c):
    return dict(c.execute('SELECT key,value FROM settings'))

def permissions(user, roles):
    if not user or user['role'] not in roles:
        raise BusinessError('You do not have permission for this action.')

def product(c, pid):
    r = c.execute('SELECT * FROM products WHERE id=? AND active=1', (pid,)).fetchone()
    if not r:
        raise BusinessError('Product not found or inactive.')
    return r

def validate_qty(p, value):
    q = number(value, 1000, 'Quantity', True)
    if p['unit'] == 'piece' and q % 1000:
        raise BusinessError(f"{p['name']}: piece quantity must be a whole number.")
    return q

def request_id(body):
    key = text(body.get('request_id'), 100, True)
    if len(key) < 16:
        raise BusinessError('Missing transaction identifier. Reload and retry.')
    return key

def movement(c, user, pid, q, kind, reference):
    c.execute('INSERT INTO movements(at,user_id,product_id,qty,kind,reference) VALUES(?,?,?,?,?,?)', (now(),user['id'],pid,q,kind,str(reference)))

def save_product(body, user):
    permissions(user, ('admin','manager'))
    barcode = text(body.get('barcode'), 80, True)
    name = text(body.get('name'), 160, True)
    unit = body.get('unit','piece')
    if unit not in ('piece','kg','litre'):
        raise BusinessError('Invalid unit.')
    price = number(body.get('price'), name='Selling price')
    cost = number(body.get('cost'), name='Cost')
    minimum = number(body.get('minimum',5),1000,'Low-stock threshold')
    with transaction() as c:
        pid = body.get('id')
        fields=(barcode,name,text(body.get('category'),80),unit,price,cost,minimum)
        if pid:
            p=product(c,pid)
            if unit != p['unit']:
                raise BusinessError('Unit cannot be changed after creation. Create a separate product.')
            c.execute('UPDATE products SET barcode=?,name=?,category=?,unit=?,price=?,cost=?,minimum=? WHERE id=?', fields+(pid,))
        else:
            if c.execute('SELECT COUNT(*) FROM products').fetchone()[0] >= 20000:
                raise BusinessError('This local edition supports up to 20,000 products.')
            q = number(body.get('stock',0),1000,'Opening stock')
            if unit == 'piece' and q % 1000:
                raise BusinessError('Piece quantity must be a whole number.')
            pid = c.execute('INSERT INTO products(barcode,name,category,unit,price,cost,minimum,stock) VALUES(?,?,?,?,?,?,?,?)',fields+(q,)).lastrowid
            if q:
                movement(c,user,pid,q,'opening','Opening stock')
        details = part_fields(body)
        c.execute('UPDATE products SET part_number=?,oem_number=?,brand=?,condition=?,rack=?,warranty_days=?,fitments_json=?,origin_country=?,description=? WHERE id=?', details+(pid,))
        audit(c,user,'product_saved' ,{'id':pid,'name':name})
        return dict(c.execute('SELECT * FROM products WHERE id=?',(pid,)).fetchone())

def adjust_stock(body,user):
    permissions(user,('admin','manager'))
    reason=text(body.get('reason'),240,True)
    with transaction() as c:
        p=product(c,body.get('product_id'))
        target=number(body.get('stock'),1000,'Counted stock')
        if p['unit']=='piece' and target%1000:
            raise BusinessError('Piece count must be a whole number.')
        diff=target-p['stock']
        c.execute('UPDATE products SET stock=? WHERE id=?',(target,p['id']))
        movement(c,user,p['id'],diff,'adjustment',reason)
        audit(c,user,'stock_adjustment',{'product':p['id'],'before':p['stock'],'after':target,'reason':reason})
        return {'ok':True}

def sale_detail(c,sid):
    r=c.execute('SELECT s.*,u.name cashier,c.name customer,c.phone customer_phone FROM sales s JOIN users u ON u.id=s.user_id LEFT JOIN customers c ON c.id=s.customer_id WHERE s.id=?',(sid,)).fetchone()
    if not r:
        raise BusinessError('Receipt not found.')
    d=dict(r)
    d['items']=rows(c,'SELECT * FROM sale_items WHERE sale_id=?',(sid,))
    for item in d['items']: item['part']=json.loads(item.pop('part_json','{}'))
    d['returns']=rows(c,'SELECT * FROM returns WHERE sale_id=? ORDER BY id DESC',(sid,))
    d['payments']=rows(c,'SELECT * FROM payments WHERE sale_id=?',(sid,))
    d['store']=json.loads(d.pop('store_json'))
    return d

def make_sale(body,user):
    permissions(user,('admin','manager','cashier'))
    key=request_id(body)
    with transaction() as c:
        old=c.execute('SELECT id FROM sales WHERE request_id=?',(key,)).fetchone()
        if old:
            return sale_detail(c,old['id'])
        items=body.get('items',[])
        if not isinstance(items,list) or not 1<=len(items)<=500:
            raise BusinessError('Add 1–500 products to the bill.')
        seen=set(); lines=[]; subtotal=0
        for item in items:
            p=product(c,item.get('product_id'))
            if p['id'] in seen:
                raise BusinessError('Combine duplicate products into one bill line.')
            seen.add(p['id']); q=validate_qty(p,item.get('qty'))
            if 'expected_price' in item and item['expected_price'] != p['price']:
                raise BusinessError(f"Price changed for {p['name']}. Refresh the register and review the bill.")
            if q>p['stock']:
                raise BusinessError(f"Insufficient stock for {p['name']}. Available: {p['stock']/1000:g} {p['unit']}.")
            line=rounded(p['price']*q)
            subtotal+=line; lines.append((p,q,line))
        discount=number(body.get('discount',0),name='Discount')
        if discount>subtotal:
            raise BusinessError('Discount cannot exceed subtotal.')
        config=settings(c)
        tax_rate=number(config['tax_rate'],name='Tax rate')
        tax=rounded((subtotal-discount)*tax_rate,10000)
        total=subtotal-discount+tax
        tendered=number(body.get('paid',0),name='Payment')
        method=body.get('method','cash')
        if method not in ('cash','card','transfer','credit'):
            raise BusinessError('Invalid payment method.')
        if tendered>total and method!='cash':
            raise BusinessError('Only cash payments can include change.')
        paid=min(total,tendered); debt=total-paid
        cid=body.get('customer_id') or None
        if cid and not c.execute('SELECT 1 FROM customers WHERE id=?',(cid,)).fetchone():
            raise BusinessError('Customer not found.')
        if debt and not cid:
            raise BusinessError('Select a customer for an unpaid/credit bill.')
        sid=c.execute('INSERT INTO sales(request_id,at,user_id,customer_id,subtotal,discount,tax,total,paid,outstanding,method,note,store_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(key,now(),user['id'],cid,subtotal,discount,tax,total,paid,debt,method,text(body.get('note'),240),json.dumps(config))).lastrowid
        remaining=total
        for i,(p,q,line) in enumerate(lines):
            allocation=remaining if i==len(lines)-1 else rounded(total*line,subtotal) if subtotal else 0
            allocation=min(remaining,allocation); remaining-=allocation
            c.execute('INSERT INTO sale_items(sale_id,product_id,name,barcode,unit,qty,price,cost,line_total,line_net) VALUES(?,?,?,?,?,?,?,?,?,?)',(sid,p['id'],p['name'],p['barcode'],p['unit'],q,p['price'],p['cost'],line,allocation))
            c.execute('UPDATE products SET stock=stock-? WHERE id=?',(q,p['id']))
            movement(c,user,p['id'],-q,'sale',sid)
        vid=body.get('vehicle_id') or None
        visit_id=body.get('workshop_visit_id') or None
        if visit_id:
            visit=c.execute("SELECT * FROM service_visits WHERE id=? AND status='completed'",(visit_id,)).fetchone()
            if not visit or visit['sale_id'] or visit['customer_id']!=cid:raise BusinessError('Workshop visit is invalid, already billed or belongs to another customer.')
            if vid and int(vid)!=visit['vehicle_id']:raise BusinessError('Selected vehicle does not match this workshop visit.')
            vid=visit['vehicle_id']
        if vid:
            vehicle=c.execute('SELECT * FROM vehicles WHERE id=? AND customer_id=?',(vid,cid)).fetchone()
            if not vehicle:raise BusinessError('Select the customer who owns this vehicle.')
            import workshop
            c.execute('UPDATE sales SET vehicle_id=?,vehicle=?,registration=? WHERE id=?',(vid,workshop.vehicle_label(vehicle),vehicle['registration'],sid))
        if visit_id:c.execute('UPDATE service_visits SET sale_id=? WHERE id=?',(sid,visit_id))
        audit(c,user,'sale',{'id':sid,'total':total})
        if not vid:c.execute('UPDATE sales SET vehicle=?,registration=? WHERE id=?',(text(body.get('vehicle'),120),text(body.get('registration'),40),sid))
        for p,q,line in lines:
            snapshot={k:p[k] for k in ('part_number','oem_number','brand','condition','warranty_days','fitments_json','origin_country','description')}
            c.execute('UPDATE sale_items SET part_json=? WHERE sale_id=? AND product_id=?',(json.dumps(snapshot),sid,p['id']))
        d=sale_detail(c,sid); d['change']=tendered-paid
        return d

def purchase(body,user):
    permissions(user,('admin','manager'))
    key=request_id(body)
    with transaction() as c:
        old=c.execute('SELECT id FROM purchases WHERE request_id=?',(key,)).fetchone()
        if old:
            return {'id':old['id'],'ok':True}
        items=body.get('items',[])
        if not isinstance(items,list) or not 1<=len(items)<=500:
            raise BusinessError('Add products to this purchase.')
        lines=[];total=0;seen=set()
        for item in items:
            p=product(c,item.get('product_id'))
            if p['id'] in seen:
                raise BusinessError('Duplicate product in purchase.')
            seen.add(p['id'])
            q=validate_qty(p,item.get('qty'));cost=number(item.get('cost'),name='Purchase unit cost')
            line=rounded(q*cost); total+=line;lines.append((p,q,cost,line))
        paid=number(body.get('paid',0),name='Payment')
        if paid>total:
            raise BusinessError('Payment exceeds purchase total.')
        supplier=body.get('supplier_id') or None
        if supplier and not c.execute('SELECT 1 FROM suppliers WHERE id=?',(supplier,)).fetchone():
            raise BusinessError('Supplier not found.')
        if paid<total and not supplier:
            raise BusinessError('Select supplier for an unpaid purchase.')
        pid=c.execute('INSERT INTO purchases(request_id,at,user_id,supplier_id,reference,total,paid) VALUES(?,?,?,?,?,?,?)',(key,now(),user['id'],supplier,text(body.get('reference'),100),total,paid)).lastrowid
        for p,q,cost,line in lines:
            avg=rounded(p['cost']*p['stock']+cost*q,p['stock']+q)
            c.execute('UPDATE products SET stock=stock+?,cost=? WHERE id=?',(q,avg,p['id']))
            c.execute('INSERT INTO purchase_items(purchase_id,product_id,qty,cost,total) VALUES(?,?,?,?,?)',(pid,p['id'],q,cost,line))
            movement(c,user,p['id'],q,'purchase',pid)
        audit(c,user,'purchase',{'id':pid,'total':total})
        return {'id':pid,'total':total,'ok':True}

def refund(body,user):
    permissions(user,('admin','manager'))
    key=request_id(body);reason=text(body.get('reason'),240,True)
    with transaction() as c:
        old=c.execute('SELECT * FROM returns WHERE request_id=?',(key,)).fetchone()
        if old:
            return dict(old)
        sale=sale_detail(c,body.get('sale_id'))
        items=body.get('items',[])
        if not isinstance(items,list) or not 1<=len(items)<=500:
            raise BusinessError('Select at least one return item.')
        lines=[];total=0;seen=set()
        for i in items:
            r=c.execute('SELECT * FROM sale_items WHERE id=? AND sale_id=?',(i.get('sale_item_id'),sale['id'])).fetchone()
            if not r or r['id'] in seen:
                raise BusinessError('Invalid or duplicate return item.')
            seen.add(r['id']);q=validate_qty(r,i.get('qty'))
            if q>r['qty']-r['returned']:
                raise BusinessError(f"Return quantity exceeds remaining quantity for {r['name']}.")
            pending=c.execute("SELECT COALESCE(SUM(qty),0) FROM warranty_claims WHERE sale_item_id=? AND status='open'",(r['id'],)).fetchone()[0]
            if q>r['qty']-r['returned']-pending:raise BusinessError('Resolve the open warranty claim before returning this quantity.')
            amount=rounded(r['line_net']*(r['returned']+q),r['qty'])-rounded(r['line_net']*r['returned'],r['qty'])
            costs=rounded(r['cost']*(r['returned']+q))-rounded(r['cost']*r['returned'])
            total+=amount;lines.append((r,q,amount,costs))
        reduction=min(sale['outstanding'],total);cash=total-reduction
        previous_total=sum(r['total'] for r in sale['returns'])
        tax_refund=rounded(sale['tax']*(previous_total+total),sale['total'])-rounded(sale['tax']*previous_total,sale['total']) if sale['total'] else 0
        rid=c.execute('INSERT INTO returns(request_id,at,user_id,sale_id,total,debt_reduction,cash_refund,tax_refund,reason) VALUES(?,?,?,?,?,?,?,?,?)',(key,now(),user['id'],sale['id'],total,reduction,cash,tax_refund,reason)).lastrowid
        c.execute('UPDATE sales SET outstanding=outstanding-? WHERE id=?',(reduction,sale['id']))
        for r,q,amount,costs in lines:
            p=c.execute('SELECT * FROM products WHERE id=?',(r['product_id'],)).fetchone()
            avg=rounded(p['cost']*p['stock']+r['cost']*q,p['stock']+q)
            c.execute('UPDATE sale_items SET returned=returned+? WHERE id=?',(q,r['id']))
            c.execute('UPDATE products SET stock=stock+?,cost=? WHERE id=?',(q,avg,p['id']))
            c.execute('INSERT INTO return_items(return_id,sale_item_id,qty,total,cost_total) VALUES(?,?,?,?,?)',(rid,r['id'],q,amount,costs))
            movement(c,user,p['id'],q,'return',rid)
        audit(c,user,'return',{'id':rid,'sale_id':sale['id'],'total':total})
        return dict(c.execute('SELECT * FROM returns WHERE id=?',(rid,)).fetchone())

def payment(body,user):
    key=request_id(body)
    target=body.get('target','sale')
    permissions(user,('admin','manager','cashier') if target=='sale' else ('admin','manager'))
    amount=number(body.get('amount'),name='Payment',positive=True)
    method=body.get('method','cash')
    if method not in ('cash','card','transfer'):
        raise BusinessError('Invalid payment method.')
    with transaction() as c:
        old=c.execute('SELECT * FROM payments WHERE request_id=?',(key,)).fetchone()
        if old:
            return dict(old)
        sid=pid=None
        if target=='sale':
            s=c.execute('SELECT * FROM sales WHERE id=?',(body.get('id'),)).fetchone()
            if not s or amount>s['outstanding']:
                raise BusinessError('Payment exceeds outstanding receipt balance or receipt not found.')
            sid=s['id'];c.execute('UPDATE sales SET outstanding=outstanding-? WHERE id=?',(amount,sid))
        elif target=='purchase':
            p=c.execute('SELECT * FROM purchases WHERE id=?',(body.get('id'),)).fetchone()
            if not p or amount>p['total']-p['paid']:
                raise BusinessError('Payment exceeds supplier balance or purchase not found.')
            pid=p['id'];c.execute('UPDATE purchases SET paid=paid+? WHERE id=?',(amount,pid))
        else:
            raise BusinessError('Invalid payment target.')
        p_id=c.execute('INSERT INTO payments(request_id,at,user_id,sale_id,purchase_id,amount,method) VALUES(?,?,?,?,?,?,?)',(key,now(),user['id'],sid,pid,amount,method)).lastrowid
        audit(c,user,'payment',{'id':p_id,'target':target,'amount':amount})
        return {'ok':True,'id':p_id}

def dashboard(c, start=None, end=None):
    start=start or datetime.now().astimezone().strftime('%Y-%m-%d')
    end=end or start
    try:
        datetime.strptime(start,'%Y-%m-%d');datetime.strptime(end,'%Y-%m-%d')
    except ValueError:
        raise BusinessError('Use valid YYYY-MM-DD report dates.')
    if start>end:
        raise BusinessError('Start date must be before end date.')
    a=start+'T00:00:00';b=end+'T23:59:59\uffff'
    s=dict(c.execute('SELECT COUNT(*) bills,COALESCE(SUM(total),0) gross_sales,COALESCE(SUM(tax),0) tax,COALESCE(SUM(paid),0) initial_collections FROM sales WHERE at BETWEEN ? AND ?',(a,b)).fetchone())
    r=c.execute('SELECT COALESCE(SUM(total),0),COALESCE(SUM(cash_refund),0) FROM returns WHERE at BETWEEN ? AND ?',(a,b)).fetchone()
    cogs=c.execute('SELECT COALESCE(SUM(ROUND(i.qty*i.cost/1000.0)),0) FROM sale_items i JOIN sales s ON i.sale_id=s.id WHERE s.at BETWEEN ? AND ?',(a,b)).fetchone()[0]
    returned_cost=c.execute('SELECT COALESCE(SUM(i.cost_total),0) FROM return_items i JOIN returns r ON i.return_id=r.id WHERE r.at BETWEEN ? AND ?',(a,b)).fetchone()[0]
    # Allocate tax to returned receipt value for period gross profit.
    return_tax=c.execute('SELECT COALESCE(SUM(tax_refund),0) FROM returns WHERE at BETWEEN ? AND ?',(a,b)).fetchone()[0]
    s.update(refunds=r[0],net_sales=s['gross_sales']-r[0],gross_profit=s['gross_sales']-r[0]-(s['tax']-return_tax)-cogs+returned_cost,tax_net=s['tax']-return_tax,cash_refunds=r[1])
    received=c.execute('SELECT COALESCE(SUM(amount),0) FROM payments WHERE sale_id IS NOT NULL AND at BETWEEN ? AND ?',(a,b)).fetchone()[0]
    s['collections']=s['initial_collections']+received-r[1]
    s['receivables']=c.execute('SELECT COALESCE(SUM(outstanding),0) FROM sales').fetchone()[0]
    s['payables']=c.execute('SELECT COALESCE(SUM(total-paid),0) FROM purchases').fetchone()[0]
    s['stock_value']=c.execute('SELECT COALESCE(SUM(ROUND(stock*cost/1000.0)),0) FROM products WHERE active=1').fetchone()[0]
    s['products']=c.execute('SELECT COUNT(*) FROM products WHERE active=1').fetchone()[0]
    low=rows(c,'SELECT * FROM products WHERE active=1 AND stock<=minimum ORDER BY stock,name LIMIT 100')
    s['low_stock_count']=c.execute('SELECT COUNT(*) FROM products WHERE active=1 AND stock<=minimum').fetchone()[0]
    s['low_stock']=low
    s['top_products']=rows(c,'SELECT i.product_id,i.name,SUM(i.qty-i.returned) qty,SUM(i.line_net-ROUND(i.line_net*i.returned*1.0/i.qty)) revenue FROM sale_items i JOIN sales s ON s.id=i.sale_id WHERE s.at BETWEEN ? AND ? GROUP BY i.product_id ORDER BY revenue DESC LIMIT 8',(a,b))
    s['daily']=rows(c,'SELECT substr(at,1,10) day,SUM(total) sales FROM sales WHERE at BETWEEN ? AND ? GROUP BY day ORDER BY day',(a,b))
    s['start']=start;s['end']=end
    return s

def save_contact(body,user,kind):
    if kind not in ('customers','suppliers'):raise BusinessError('Invalid contact type.')
    permissions(user,('admin','manager','cashier') if kind=='customers' else ('admin','manager'))
    with transaction() as c:
        name=text(body.get('name'),100,True);phone=text(body.get('phone'),30)
        cid=body.get('id')
        if cid:
            if not c.execute(f'SELECT id FROM {kind} WHERE id=?',(cid,)).fetchone():raise BusinessError('Contact not found.')
            c.execute(f'UPDATE {kind} SET name=?,phone=? WHERE id=?',(name,phone,cid))
        else:cid=c.execute(f'INSERT INTO {kind}(name,phone) VALUES(?,?)',(name,phone)).lastrowid
        if kind=='customers':
            values=tuple(text(body.get(k),limit) for k,limit in [('email',120),('address',300),('company',120),('vehicle',120),('registration',40),('notes',1000)])
            c.execute('UPDATE customers SET email=?,address=?,company=?,vehicle=?,registration=?,notes=? WHERE id=?',values+(cid,))
        audit(c,user,kind+'_saved',{'id':cid})
        return {'id':cid,'ok':True}

def seed_demo(user):
    permissions(user,('admin',))
    demo=[('990000000001','Demo Front Brake Pad Set','Braking','piece',6500,4800,12,4),('990000000002','Demo Oil Filter','Filters','piece',1450,950,25,8),('990000000003','Demo Spark Plug','Ignition','piece',2200,1500,36,12),('990000000004','Demo Air Filter','Filters','piece',1800,1250,15,5),('990000000005','Demo Engine Oil 5W-30 4L','Lubricants','piece',8500,6800,10,4),('990000000006','Demo Headlamp Assembly','Lighting','piece',18500,14000,3,2),('990000000007','Demo Front Shock Absorber','Suspension','piece',12500,9500,6,2),('990000000008','Demo Drive Belt','Engine','piece',3200,2300,2,5),('990000000009','Demo Wheel Bearing','Drivetrain','piece',4800,3500,8,3),('990000000010','Demo Radiator Hose','Cooling','piece',2400,1650,7,3),('990000000011','Demo Wiper Blade Pair','Accessories','piece',1900,1200,20,5),('990000000012','Demo Battery 12V','Electrical','piece',22000,18500,4,2)]
    with transaction() as c:
        if c.execute('SELECT COUNT(*) FROM products').fetchone()[0]:
            raise BusinessError('Demo can only be loaded into an empty product catalog.')
        for barcode,name,category,unit,price,cost,stock,minimum in demo:
            pid=c.execute('INSERT INTO products(barcode,name,category,unit,price,cost,stock,minimum) VALUES(?,?,?,?,?,?,?,?)',(barcode,name,category,unit,price*100,cost*100,stock*1000,minimum*1000)).lastrowid
            fitments=[{'make':'Demo Motors','model':'Sedan','year_from':2015,'year_to':2025,'engine':'1.6 petrol'}]
            c.execute('UPDATE products SET part_number=?,oem_number=?,brand=?,rack=?,warranty_days=?,fitments_json=? WHERE id=?',('DEMO-'+str(pid).zfill(4),'EXAMPLE-'+str(pid),'DemoLine','A'+str((pid-1)//4+1)+'-'+str(pid),180,json.dumps(fitments),pid))
            c.execute('UPDATE products SET origin_country=?,description=? WHERE id=?',('Example country','Fictional demonstration part. Verify real specifications and fitment before sale.',pid))
            movement(c,user,pid,stock*1000,'opening','Demo stock')
        c.execute("INSERT INTO customers(name,phone) VALUES('Demo Customer','03000000000')")
        c.execute("INSERT INTO suppliers(name,phone) VALUES('Demo Supplier','03000000001')")
        audit(c,user,'demo_loaded',{})
    return {'ok':True}

def backup(user):
    permissions(user,('admin',))
    folder=DATA/'backups';folder.mkdir(exist_ok=True)
    path=folder/f'autoparts-{datetime.now().strftime("%Y%m%d-%H%M%S")}-{secrets.token_hex(3)}.sqlite3'
    with connect() as src, sqlite3.connect(path, factory=ClosingConnection) as dest:
        src.backup(dest)
        if dest.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
            raise BusinessError('Backup integrity check failed.')
    with transaction() as c:
        audit(c,user,'backup',{'filename':path.name})
    return path

def import_csv(content,user):
    permissions(user,('admin','manager'))
    try:
        parsed=list(csv.DictReader(io.StringIO(content.lstrip('\ufeff'))))
        if not 1<=len(parsed)<=10000:
            raise BusinessError('CSV must contain 1–10,000 products.')
        normalized=[];extras=[];seen=set()
        for index,r in enumerate(parsed,2):
            try:
                barcode=text(r.get('barcode'),80,True);name=text(r.get('name'),160,True)
                if barcode in seen:
                    raise BusinessError('Duplicate barcode in file.')
                seen.add(barcode);unit=r.get('unit','piece').strip()
                if unit not in ('piece','kg','litre'):
                    raise BusinessError('Invalid unit.')
                q=number(r.get('stock',0),1000,'Opening stock')
                if unit=='piece' and q%1000:
                    raise BusinessError('Piece quantity must be whole.')
                extras.append(part_fields(r))
                normalized.append((barcode,name,text(r.get('category'),80),unit,number(r.get('price'),name='Price'),number(r.get('cost'),name='Cost'),q,number(r.get('minimum',5),1000,'Minimum')))
            except BusinessError as e:
                raise BusinessError(f'CSV row {index}: {e}')
        with transaction() as c:
            if c.execute('SELECT COUNT(*) FROM products').fetchone()[0]+len(normalized)>20000:
                raise BusinessError('Import would exceed the 20,000-product local edition limit.')
            for r, details in zip(normalized, extras):
                if c.execute('SELECT 1 FROM products WHERE barcode=?',(r[0],)).fetchone():
                    raise BusinessError(f'Barcode {r[0]} already exists. Import is for new products only; nothing was imported.')
                pid=c.execute('INSERT INTO products(barcode,name,category,unit,price,cost,stock,minimum) VALUES(?,?,?,?,?,?,?,?)',r).lastrowid
                c.execute('UPDATE products SET part_number=?,oem_number=?,brand=?,condition=?,rack=?,warranty_days=?,fitments_json=?,origin_country=?,description=? WHERE id=?',details+(pid,))
                if r[6]:movement(c,user,pid,r[6],'opening','CSV import')
            audit(c,user,'csv_import',{'count':len(normalized)})
        return {'ok':True,'count':len(normalized)}
    except csv.Error:
        raise BusinessError('Invalid CSV file.')

# AutoParts extension: catalog fitment is shop-entered, never an OEM guarantee.
WARRANTY_SCHEMA = '''
CREATE TABLE IF NOT EXISTS warranty_claims(id INTEGER PRIMARY KEY,request_id TEXT UNIQUE NOT NULL,at TEXT NOT NULL,user_id INTEGER NOT NULL REFERENCES users(id),sale_item_id INTEGER NOT NULL REFERENCES sale_items(id),qty INTEGER NOT NULL CHECK(qty>0),reason TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','approved','rejected','closed')),resolution TEXT NOT NULL DEFAULT '',updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_warranty_sale_item ON warranty_claims(sale_item_id);
'''
PART_COLUMNS=('part_number','oem_number','brand','condition','rack','warranty_days','fitments_json','origin_country','description')

def integer(value, name, low=0, high=3650):
    try:
        n=int(str(value))
        if not low<=n<=high:raise ValueError()
        return n
    except (ValueError,TypeError):raise BusinessError(f'{name} must be a whole number between {low} and {high}.')

def parse_fitments(value):
    if isinstance(value,str):
        if not value.strip():return []
        try: value=json.loads(value)
        except json.JSONDecodeError:
            lines=value.splitlines();value=[]
            for line in lines:
                if not line.strip():continue
                cols=[x.strip() for x in line.split('|')]
                if len(cols)!=5:raise BusinessError('Compatibility: each line needs Make | Model | From year | To year | Engine.')
                value.append(dict(zip(('make','model','year_from','year_to','engine'),cols)))
    if not isinstance(value,list) or len(value)>100:raise BusinessError('Enter up to 100 compatibility entries.')
    result=[]
    for entry in value:
        if not isinstance(entry,dict):raise BusinessError('Invalid compatibility entry.')
        a=integer(entry.get('year_from'),'From year',1950,2100);b=integer(entry.get('year_to'),'To year',1950,2100)
        if b<a:raise BusinessError('Compatibility end year must be after or equal to start year.')
        result.append({'make':text(entry.get('make'),60,True),'model':text(entry.get('model'),80,True),'year_from':a,'year_to':b,'engine':text(entry.get('engine'),80)})
    return result

def part_fields(body):
    condition=body.get('condition') or 'aftermarket'
    if condition not in ('genuine','aftermarket','used','reconditioned'):raise BusinessError('Invalid part condition.')
    return (text(body.get('part_number'),100),text(body.get('oem_number'),160),text(body.get('brand'),80),condition,text(body.get('rack'),60),integer(body.get('warranty_days') or 0,'Warranty days'),json.dumps(parse_fitments(body.get('fitments',body.get('fitments_json',[])))),text(body.get('origin_country'),80),text(body.get('description'),2000))

def find_parts(c, make='', model='', year='', engine='', query=''):
    make=text(make,60).casefold();model=text(model,80).casefold();engine=text(engine,80).casefold();query=text(query,160).casefold()
    y=integer(year,'Vehicle year',1950,2100) if str(year).strip() else None
    matches=[]
    for p in rows(c,'SELECT * FROM products WHERE active=1 ORDER BY name LIMIT 20000'):
        if query and query not in ' '.join(str(p[k]) for k in ('name','barcode','part_number','oem_number','brand','rack','origin_country','description')).casefold():continue
        entries=json.loads(p['fitments_json'])
        fitting=[f for f in entries if (not make or f['make'].casefold()==make) and (not model or f['model'].casefold()==model) and (y is None or f['year_from']<=y<=f['year_to']) and (not engine or engine in f['engine'].casefold())]
        if (make or model or y is not None or engine) and not fitting:continue
        p['matched_fitments']=fitting;p.pop('cost',None);matches.append(p)
    return matches[:500]

def new_recovery(c, user_id):
    code='AP-'+secrets.token_hex(16).upper()
    c.execute('UPDATE users SET recovery_hash=? WHERE id=?',(password_hash(code),user_id))
    return code

def recover_account(body):
    code=text(body.get('code'),80,True).upper()
    with transaction() as c:
        users=c.execute("SELECT * FROM users WHERE active=1 AND recovery_hash<>''").fetchall()
        # Single installed owner plus bounded staff; code is 128 random bits.
        target=next((u for u in users if verify_password(code,u['recovery_hash'])),None)
        if not target:raise BusinessError('Recovery code is incorrect or has been replaced. Ask the shop owner for help.')
        action=body.get('action','username')
        if action not in ('username','password'):raise BusinessError('Invalid recovery action.')
        if action=='username':return {'username':target['username']}
        password=str(body.get('password',''))
        if password!=str(body.get('confirm','')):raise BusinessError('Passwords do not match.')
        c.execute('UPDATE users SET password=? WHERE id=?',(password_hash(password),target['id']))
        fresh=new_recovery(c,target['id'])
        audit(c,dict(target),'account_recovered',{})
        return {'username':target['username'],'recovery_code':fresh,'user_id':target['id']}

def warranty_claim(body,user):
    permissions(user,('admin','manager'))
    with transaction() as c:
        if body.get('id'):
            claim=c.execute('SELECT * FROM warranty_claims WHERE id=?',(body['id'],)).fetchone()
            if not claim:raise BusinessError('Warranty claim not found.')
            status=body.get('status')
            if status not in ('approved','rejected','closed'):raise BusinessError('Choose approved, rejected or closed.')
            if claim['status'] not in ('open','approved') or (claim['status']=='approved' and status!='closed'):
                raise BusinessError('This claim is already resolved or has an invalid transition.')
            resolution=text(body.get('resolution'),500,True)
            c.execute('UPDATE warranty_claims SET status=?,resolution=?,updated_at=? WHERE id=?',(status,resolution,now(),claim['id']))
            audit(c,user,'warranty_updated',{'id':claim['id'],'status':status})
            return {'ok':True,'id':claim['id']}
        key=request_id(body)
        old=c.execute('SELECT id FROM warranty_claims WHERE request_id=?',(key,)).fetchone()
        if old:return {'ok':True,'id':old['id']}
        line=c.execute('SELECT i.*,s.at FROM sale_items i JOIN sales s ON s.id=i.sale_id WHERE i.id=?',(body.get('sale_item_id'),)).fetchone()
        if not line:raise BusinessError('Original sale item not found.')
        part=json.loads(line['part_json']);days=part.get('warranty_days',0)
        if not days:raise BusinessError('No warranty was recorded for this item at the time of sale.')
        if datetime.now().astimezone()>datetime.fromisoformat(line['at'])+timedelta(days=days):raise BusinessError('The recorded warranty period has expired.')
        q=validate_qty(line,body.get('qty'))
        reserved=c.execute("SELECT COALESCE(SUM(qty),0) FROM warranty_claims WHERE sale_item_id=? AND status<>'rejected'",(line['id'],)).fetchone()[0]
        if q>line['qty']-line['returned']-reserved:raise BusinessError('Claim quantity exceeds unreturned, unclaimed sale quantity.')
        reason=text(body.get('reason'),500,True)
        cid=c.execute('INSERT INTO warranty_claims(request_id,at,user_id,sale_item_id,qty,reason,updated_at) VALUES(?,?,?,?,?,?,?)',(key,now(),user['id'],line['id'],q,reason,now())).lastrowid
        audit(c,user,'warranty_opened',{'id':cid,'sale_item':line['id'],'qty':q})
        return {'ok':True,'id':cid}
