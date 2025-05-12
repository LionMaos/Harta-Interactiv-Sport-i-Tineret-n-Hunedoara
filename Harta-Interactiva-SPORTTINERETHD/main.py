from flask import Flask, render_template, request, redirect, url_for, jsonify
from flask_sqlalchemy import SQLAlchemy
import firebase_admin
from firebase_admin import credentials, firestore
import folium
import json

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///facilities.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Inițializare Firebase
try:
    cred = credentials.Certificate('/etc/secrets/firebase-key.json')
    firebase_admin.initialize_app(cred)
    firestore_db = firestore.client()
    firebase_enabled = True
except Exception as e:
    print("Firebase error:", e)
    firebase_enabled = False


class SportFacility(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    address = db.Column(db.String(200))
    phone = db.Column(db.String(20))
    website = db.Column(db.String(200))
    email = db.Column(db.String(100))
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    facility_type = db.Column(db.String(50))
    category = db.Column(db.String(50))
    sections = db.relationship('SportSection', backref='facility', lazy=True)
    sports_list = db.Column(db.Text)
    target_group = db.Column(db.String(200))
    activities_description = db.Column(db.Text)


class SportSection(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    facility_id = db.Column(db.Integer, db.ForeignKey('sport_facility.id'))


def load_from_firebase():
    if not firebase_enabled:
        return

    try:
        facilities = firestore_db.collection('facilities').stream()
        with app.app_context():
            for facility_doc in facilities:
                facility_data = facility_doc.to_dict()
                facility = SportFacility.query.get(int(facility_doc.id))

                if not facility:
                    facility = SportFacility()
                    facility.id = int(facility_doc.id)
                    db.session.add(facility)

                # Update facility fields
                facility.name = facility_data.get('name')
                facility.address = facility_data.get('address')
                facility.phone = facility_data.get('phone')
                facility.website = facility_data.get('website')
                facility.email = facility_data.get('email')
                facility.latitude = facility_data.get('latitude')
                facility.longitude = facility_data.get('longitude')
                facility.facility_type = facility_data.get('facility_type')
                facility.category = facility_data.get('category')
                facility.sports_list = facility_data.get('sports_list')
                facility.target_group = facility_data.get('target_group')
                facility.activities_description = facility_data.get(
                    'activities_description')

                # Handle sections
                if 'sections' in facility_data:
                    SportSection.query.filter_by(
                        facility_id=facility.id).delete()
                    for section_data in facility_data['sections']:
                        section = SportSection(name=section_data['name'],
                                               facility_id=facility.id)
                        db.session.add(section)

            db.session.commit()
    except Exception as e:
        print("Firebase load error:", e)


def init_db():
    with app.app_context():
        if not database_exists():
            db.create_all()
        load_from_firebase()


def save_to_firebase(facility):
    if not firebase_enabled:
        return False

    try:
        # Pregătim datele complete pentru salvare
        facility_data = {
            'name':
            facility.name,
            'address':
            facility.address,
            'phone':
            facility.phone,
            'website':
            facility.website,
            'email':
            facility.email,
            'latitude':
            facility.latitude,
            'longitude':
            facility.longitude,
            'facility_type':
            facility.facility_type,
            'category':
            facility.category,
            'sports_list':
            facility.sports_list,
            'target_group':
            facility.target_group,
            'activities_description':
            facility.activities_description,
            'sections': [{
                'name': section.name
            } for section in facility.sections] if facility.sections else []
        }

        # Salvare atomică în Firebase
        doc_ref = firestore_db.collection('facilities').document(
            str(facility.id))
        doc_ref.set(facility_data, merge=True)
        return True

    except Exception as e:
        print("Firebase save error:", e)
        return False


def database_exists():
    try:
        SportFacility.query.first()
        SportSection.query.first()
        return True
    except:
        return False


init_db()


@app.route('/')
def index():
    facility_type = request.args.get('type', 'all')
    category = request.args.get('category')

    m = folium.Map(location=[45.8, 23.0], zoom_start=9)
    query = SportFacility.query

    if facility_type != 'all':
        query = query.filter_by(facility_type=facility_type)
    if category:
        query = query.filter_by(category=category)

    facilities = query.all()

    for facility in facilities:
        color = {
            'sport': 'red',
            'ong': 'green',
            'DJST HD': 'blue'
        }.get(facility.facility_type, 'gray')

        popup_content = f"""
            <strong>{facility.name}</strong><br>
            Adresa: {facility.address}<br>
            Telefon: {facility.phone}<br>
            {f'Website: <a href="{facility.website if facility.website.startswith("http") else "https://" + facility.website}" target="_blank">{facility.website}</a><br>' if facility.website else ''}
            {f'Email: <a href="mailto:{facility.email}">{facility.email}</a><br>' if facility.email else ''}
        """

        if facility.facility_type == 'sport' and facility.category == 'structuri_sportive':
            popup_content += "<br><strong>Secții sportive:</strong><br>"
            for section in facility.sections:
                popup_content += f"- {section.name}<br>"
        if facility.facility_type == 'sport' and facility.category not in [
                'structuri_sportive', 'tenis'
        ]:
            if facility.sports_list:
                sports = facility.sports_list.split(',')
                popup_content += "<br><br>Sporturi ce se pot practica:"
                for sport in sports:
                    if sport.strip():
                        popup_content += f"<br>• {sport.strip()}"
        elif facility.facility_type == 'ong':
            if facility.target_group:
                popup_content += f"<br>Grup țintă: {facility.target_group}"
            if facility.activities_description:
                popup_content += f"<br>Descriere activități: {facility.activities_description}"

        folium.Marker([facility.latitude, facility.longitude],
                      popup=popup_content,
                      icon=folium.Icon(color=color)).add_to(m)

    return render_template('index.html',
                           map=m._repr_html_(),
                           active_type=facility_type)


@app.route('/admin', methods=['GET', 'POST'])
def admin():
    if request.method == 'POST':
        if 'delete' in request.form:
            facility = SportFacility.query.get(request.form['delete'])
            if facility:
                db.session.delete(facility)
                db.session.commit()
        else:
            facility_id = request.form.get('facility_id')
            if facility_id:
                facility = SportFacility.query.get(facility_id)
            else:
                facility = SportFacility()

            facility.name = request.form['name']
            facility.address = request.form['address']
            facility.phone = request.form['phone']
            facility.website = request.form.get('website', '')
            facility.email = request.form.get('email', '')
            facility.latitude = float(request.form['latitude'])
            facility.longitude = float(request.form['longitude'])
            facility.facility_type = request.form['type']
            facility.category = request.form.get('category', '')

            if not facility_id:
                db.session.add(facility)
            db.session.commit()

            # Salvare în Firebase (paralel cu SQLite)
            save_to_firebase(facility)

            if facility.facility_type == 'sport' and facility.category == 'structuri_sportive':
                SportSection.query.filter_by(facility_id=facility.id).delete()
                section_names = request.form.getlist('section_names[]')
                for section_name in section_names:
                    if section_name.strip():
                        section = SportSection(name=section_name,
                                               facility_id=facility.id)
                        db.session.add(section)
                db.session.commit()
            elif facility.facility_type == 'sport' and facility.category not in [
                    'structuri_sportive', 'tenis'
            ]:
                sports = request.form.getlist('sports[]')
                facility.sports_list = ','.join(filter(None, sports))
                db.session.commit()
            elif facility.facility_type == 'ong':
                facility.target_group = request.form.get('target_group', '')
                facility.activities_description = request.form.get(
                    'activities_description', '')
                db.session.commit()

        return redirect(url_for('admin'))

    facilities = SportFacility.query.all()
    return render_template('admin.html', facilities=facilities)


@app.route('/api/facilities/<int:id>')
def get_facility(id):
    facility = db.session.get(SportFacility, id)
    if facility:
        sections_data = [{
            'name': section.name
        } for section in facility.sections]
        return jsonify({
            'id':
            facility.id,
            'name':
            facility.name,
            'address':
            facility.address,
            'phone':
            facility.phone,
            'website':
            facility.website,
            'email':
            facility.email,
            'latitude':
            facility.latitude,
            'longitude':
            facility.longitude,
            'facility_type':
            facility.facility_type,
            'category':
            facility.category,
            'target_group':
            facility.target_group,
            'activities_description':
            facility.activities_description,
            'sections':
            sections_data,
            'sports_list':
            facility.sports_list if facility.sports_list else ''
        })
    return jsonify({'error': 'Facility not found'}), 404


@app.route('/ong_data')
def ong_data():
    return redirect(url_for('index', type='ong'))


@app.route('/djst_data')
def djst_data():
    facility = SportFacility.query.filter_by(facility_type='DJST HD').first()
    if facility:
        return redirect(
            url_for('index',
                    type='DJST HD',
                    lat=facility.latitude,
                    lon=facility.longitude))
    return redirect(url_for('index', type='DJST HD'))


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
