"""Vehicle service history and shop-entered oil schedules; no automatic billing."""
from datetime import datetime, timedelta
import core as db

SCHEMA='''
CREATE TABLE IF NOT EXISTS vehicles(id INTEGER PRIMARY KEY,customer_id INTEGER NOT NULL REFERENCES customers(id),make TEXT NOT NULL DEFAULT '',model TEXT NOT NULL,year INTEGER,registration TEXT NOT NULL DEFAULT '',engine TEXT NOT NULL DEFAULT '',chassis TEXT NOT NULL DEFAULT '',notes TEXT NOT NULL DEFAULT '',legacy_customer_id INTEGER UNIQUE,created_at TEXT NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS idx_vehicle_registration ON vehicles(customer_id,registration COLLATE NOCASE) WHERE registration<>'';
CREATE TABLE IF NOT EXISTS service_visits(id INTEGER PRIMARY KEY,request_id TEXT UNIQUE NOT NULL,customer_id INTEGER NOT NULL REFERENCES customers(id),vehicle_id INTEGER NOT NULL REFERENCES vehicles(id),user_id INTEGER NOT NULL REFERENCES users(id),visit_at TEXT NOT NULL,odometer INTEGER NOT NULL CHECK(odometer>=0),work_done TEXT NOT NULL,oil_changed INTEGER NOT NULL CHECK(oil_changed IN (0,1)),oil_brand TEXT NOT NULL DEFAULT '',oil_grade TEXT NOT NULL DEFAULT '',oil_quantity INTEGER NOT NULL DEFAULT 0,filter_note TEXT NOT NULL DEFAULT '',next_oil_at TEXT NOT NULL DEFAULT '',next_oil_km INTEGER,technician TEXT NOT NULL DEFAULT '',notes TEXT NOT NULL DEFAULT '',sale_id INTEGER UNIQUE REFERENCES sales(id),status TEXT NOT NULL DEFAULT 'completed' CHECK(status IN ('completed','void')),void_reason TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_visit_vehicle_at ON service_visits(vehicle_id,visit_at,id);
CREATE INDEX IF NOT EXISTS idx_visit_customer ON service_visits(customer_id);
CREATE INDEX IF NOT EXISTS idx_sale_items_product ON sale_items(product_id);
'''

def initialize(c):
    c.executescript(SCHEMA)
    # Preserve old free-text customer vehicle data exactly; do not guess its make/year.
    c.execute("INSERT OR IGNORE INTO vehicles(customer_id,model,registration,legacy_customer_id,created_at) SELECT id,CASE WHEN vehicle='' THEN 'Vehicle details pending' ELSE vehicle END,registration,id,? FROM customers WHERE (vehicle<>'' OR registration<>'') AND NOT EXISTS(SELECT 1 FROM vehicles v WHERE v.customer_id=customers.id)",(db.now(),))

def vehicle_label(v):
    return ' '.join(str(v[k]) for k in ('make','model','year') if v[k] not in ('',None))

def save_vehicle(body,user):
    db.permissions(user,('admin','manager','cashier'))
    cid=db.integer(body.get('customer_id'),'Customer ID',1,1000000000)
    year=db.integer(body['year'],'Model year',1950,2100) if str(body.get('year','')).strip() else None
    fields=(db.text(body.get('make'),60),db.text(body.get('model'),120,True),year,db.text(body.get('registration'),40).upper(),db.text(body.get('engine'),80),db.text(body.get('chassis'),60),db.text(body.get('notes'),1000))
    with db.transaction() as c:
        if not c.execute('SELECT id FROM customers WHERE id=?',(cid,)).fetchone():raise db.BusinessError('Customer not found.')
        vid=body.get('id')
        if vid:
            if not c.execute('SELECT id FROM vehicles WHERE id=? AND customer_id=?',(vid,cid)).fetchone():raise db.BusinessError('Vehicle not found for this customer.')
            c.execute('UPDATE vehicles SET make=?,model=?,year=?,registration=?,engine=?,chassis=?,notes=? WHERE id=?',fields+(vid,))
        else:vid=c.execute('INSERT INTO vehicles(customer_id,make,model,year,registration,engine,chassis,notes,created_at) VALUES(?,?,?,?,?,?,?,?,?)',(cid,)+fields+(db.now(),)).lastrowid
        v=dict(c.execute('SELECT * FROM vehicles WHERE id=?',(vid,)).fetchone())
        # Keep the existing POS/customer list useful without breaking old data.
        first=c.execute('SELECT id FROM vehicles WHERE customer_id=? ORDER BY id LIMIT 1',(cid,)).fetchone()[0]
        if first==int(vid):c.execute('UPDATE customers SET vehicle=?,registration=? WHERE id=?',(vehicle_label(v),v['registration'],cid))
        db.audit(c,user,'vehicle_saved',{'id':vid,'customer_id':cid})
        return {'ok':True,'id':vid,'customer_id':cid}

def parse_instant(value,name):
    try:
        t=datetime.fromisoformat(str(value))
        if t.tzinfo is None:t=t.astimezone()
        return t
    except (ValueError,TypeError):raise db.BusinessError(f'{name}: select a valid date and time.')

def save_visit(body,user):
    db.permissions(user,('admin','manager','cashier'))
    key=db.request_id(body);vid=db.integer(body.get('vehicle_id'),'Vehicle',1,1000000000)
    at=parse_instant(body.get('visit_at'),'Visit');at=at.astimezone()
    if at>datetime.now().astimezone()+timedelta(minutes=5):raise db.BusinessError('A completed visit cannot have a future date. Use next oil date for the upcoming appointment.')
    km=db.integer(body.get('odometer'),'Current mileage',0,10000000)
    changed=body.get('oil_changed') in (True,1,'1','on','true')
    next_at=parse_instant(body['next_oil_at'],'Next oil change').astimezone() if changed and body.get('next_oil_at') else None
    next_km=db.integer(body['next_oil_km'],'Next oil mileage',1,10000000) if changed and str(body.get('next_oil_km','')).strip() else None
    if next_at and next_at<=at:raise db.BusinessError('Next oil-change date/time must be after this visit.')
    if next_km is not None and next_km<=km:raise db.BusinessError('Next oil-change mileage must be higher than the current mileage.')
    if changed and not next_at and next_km is None:raise db.BusinessError('For an oil change, enter a next date/time or next mileage.')
    quantity=db.number(body.get('oil_quantity') or 0,1000,'Oil quantity') if changed else 0
    with db.transaction() as c:
        old=c.execute('SELECT id,customer_id FROM service_visits WHERE request_id=?',(key,)).fetchone()
        if old:return {'ok':True,'id':old['id'],'customer_id':old['customer_id']}
        v=c.execute('SELECT * FROM vehicles WHERE id=?',(vid,)).fetchone()
        if not v:raise db.BusinessError('Vehicle not found. Add it under Customer details first.')
        cid=v['customer_id']
        if body.get('customer_id') and int(body['customer_id'])!=cid:raise db.BusinessError('The vehicle belongs to a different customer.')
        stamp=at.isoformat(timespec='seconds')
        # Backdated history is allowed; chronological mileage must remain consistent.
        before=c.execute("SELECT odometer FROM service_visits WHERE vehicle_id=? AND status='completed' AND visit_at<=? ORDER BY visit_at DESC,id DESC LIMIT 1",(vid,stamp)).fetchone()
        after=c.execute("SELECT odometer FROM service_visits WHERE vehicle_id=? AND status='completed' AND visit_at>? ORDER BY visit_at,id LIMIT 1",(vid,stamp)).fetchone()
        if (before and km<before['odometer']) or (after and km>after['odometer']):raise db.BusinessError('Mileage conflicts with this vehicle’s visit history. Check mileage or visit date.')
        sid=db.integer(body['sale_id'],'Receipt number',1,1000000000) if str(body.get('sale_id','')).strip() else None
        if sid:
            sale=c.execute('SELECT customer_id,vehicle_id FROM sales WHERE id=?',(sid,)).fetchone()
            if not sale or sale['customer_id']!=cid or (sale['vehicle_id'] and sale['vehicle_id']!=vid):raise db.BusinessError('The receipt must belong to this customer and vehicle.')
        values=(key,cid,vid,user['id'],stamp,km,db.text(body.get('work_done'),2000,True),int(changed),db.text(body.get('oil_brand'),100) if changed else '',db.text(body.get('oil_grade'),60) if changed else '',quantity,db.text(body.get('filter_note'),240) if changed else '',next_at.isoformat(timespec='seconds') if next_at else '',next_km,db.text(body.get('technician'),100),db.text(body.get('notes'),1000),sid,db.now())
        ident=c.execute('INSERT INTO service_visits(request_id,customer_id,vehicle_id,user_id,visit_at,odometer,work_done,oil_changed,oil_brand,oil_grade,oil_quantity,filter_note,next_oil_at,next_oil_km,technician,notes,sale_id,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',values).lastrowid
        if sid:c.execute('UPDATE sales SET vehicle_id=?,vehicle=?,registration=? WHERE id=?',(vid,vehicle_label(v),v['registration'],sid))
        db.audit(c,user,'workshop_visit_saved',{'id':ident,'customer_id':cid,'vehicle_id':vid,'oil_changed':changed})
        return {'ok':True,'id':ident,'customer_id':cid}

def void_visit(body,user):
    db.permissions(user,('admin','manager'))
    reason=db.text(body.get('reason'),500,True)
    with db.transaction() as c:
        visit=c.execute("SELECT * FROM service_visits WHERE id=? AND status='completed'",(body.get('id'),)).fetchone()
        if not visit:raise db.BusinessError('Completed visit not found.')
        c.execute("UPDATE service_visits SET status='void',void_reason=? WHERE id=?",(reason,visit['id']))
        db.audit(c,user,'workshop_visit_void',{'id':visit['id'],'reason':reason})
        return {'ok':True,'customer_id':visit['customer_id']}

def visit_rows(c,cid=None,limit=300):
    return db.rows(c,"SELECT w.*,cu.name customer,cu.phone,v.make,v.model,v.year,v.registration,v.engine,u.name recorded_by FROM service_visits w JOIN customers cu ON cu.id=w.customer_id JOIN vehicles v ON v.id=w.vehicle_id JOIN users u ON u.id=w.user_id WHERE ? IS NULL OR w.customer_id=? ORDER BY w.visit_at DESC,w.id DESC LIMIT ?",(cid,cid,limit))

def vehicle_summaries(c,cid=None):
    vehicles=db.rows(c,'SELECT v.*,cu.name customer,cu.phone FROM vehicles v JOIN customers cu ON cu.id=v.customer_id WHERE ? IS NULL OR v.customer_id=? ORDER BY cu.name,v.id',(cid,cid))
    recent={};oil={}
    for row in db.rows(c,"SELECT * FROM service_visits WHERE status='completed' ORDER BY visit_at DESC,id DESC"):
        recent.setdefault(row['vehicle_id'],row)
        if row['oil_changed']:oil.setdefault(row['vehicle_id'],row)
    current=datetime.now().astimezone()
    for v in vehicles:
        v['label']=vehicle_label(v);v['last_visit']=recent.get(v['id']);v['last_oil']=oil.get(v['id']);v['due_status']='not_set';v['due_by_date']=False;v['due_by_mileage']=False
        if v['last_oil']:
            o=v['last_oil'];due=parse_instant(o['next_oil_at'],'Next oil date') if o['next_oil_at'] else None
            mileage=v['last_visit']['odometer'] if v['last_visit'] else o['odometer']
            v['due_by_date']=bool(due and due<=current);v['due_by_mileage']=bool(o['next_oil_km'] is not None and mileage>=o['next_oil_km'])
            if v['due_by_date'] or v['due_by_mileage']:v['due_status']='due'
            elif (due and due<=current+timedelta(days=7)) or (o['next_oil_km'] is not None and o['next_oil_km']-mileage<=500):v['due_status']='soon'
            else:v['due_status']='scheduled'
    return vehicles
