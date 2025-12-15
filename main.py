import os
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from typing import List
from geopy.geocoders import Nominatim
from geopy.distance import geodesic
import openrouteservice
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas     
import requests
import mysql.connector
from mysql.connector import Error
from dotenv import load_dotenv
import pandas as pd
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

load_dotenv()

app = FastAPI()
# Mount static folder
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
templates.env.globals['static'] = "/static"

# ------------------- DATABASE CONNECTION -------------------
def get_db_connection():
    try:
        conn = mysql.connector.connect(
            host="localhost",
            user="root",        
            password="umer1234",        # apna MySQL password
            database="smart_ambulance_db"
        )
        return conn
    except Error as e:
        print(f"DB Connection error: {e}")
        return None

# ORS client
ORS_API_KEY = os.getenv("ORS_API_KEY")
client = openrouteservice.Client(key=ORS_API_KEY)

# Geocoder
geolocator = Nominatim(user_agent="smart-ambulance-osm")


# ------------------- UTILS -------------------
def get_coordinates(place_name):
    try:
        if "," in place_name:
            lat, lon = map(float, place_name.split(","))
            return (lat, lon)
        location = geolocator.geocode(place_name)
        if location:
            return (location.latitude, location.longitude)
    except Exception as e:
        print(f"Geocoding error: {e}")
    return None

def get_eta_and_geometry(origin, destination):
    try:
        coords = [origin[::-1], destination[::-1]]  # ORS uses (lon, lat)
        route = client.directions(
            coords,
            profile='driving-car',
            format='geojson',
            radiuses=[2000, 2000]
        )
        eta = route['features'][0]['properties']['summary']['duration']
        geometry = route['features'][0]['geometry']
        return eta, geometry
    except Exception as e:
        print(f"Routing error: {e}")
        return float('inf'), None

def find_nearest_hospitals(origin_coord, radius_km=5, limit=3):
    lat, lon = origin_coord
    overpass_url = "http://overpass-api.de/api/interpreter"
    query = f"""
    [out:json][timeout:25];
    node["amenity"="hospital"](around:{int(radius_km*1000)},{lat},{lon});
    out body;
    """
    try:
        response = requests.get(overpass_url, params={'data': query}, timeout=30)
        response.raise_for_status()
        data = response.json()
        hospitals = []
        for element in data.get("elements", []):
            hosp_lat = element['lat']
            hosp_lon = element['lon']
            hosp_name = element['tags'].get('name', 'Unnamed Hospital')
            distance = geodesic(origin_coord, (hosp_lat, hosp_lon)).km
            hospitals.append({
                "name": hosp_name,
                "lat": hosp_lat,
                "lon": hosp_lon,
                "distance_km": round(distance, 2)
            })

        hospitals.sort(key=lambda x: x["distance_km"])
        return hospitals[:limit]
    except Exception as e:
        print(f"Overpass error: {e}")
        return []

@app.get("/nearest_hospitals")
def nearest_hospitals(lat: float, lon: float, radius_km: float = 5, limit: int = 3):
    hospitals = find_nearest_hospitals((lat, lon), radius_km, limit)
    return JSONResponse(content={"hospitals": hospitals})

def get_all_hospitals():
    conn = get_db_connection()
    hospitals = []
    if conn:
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT hospital_id, name FROM hospitals")
            hospitals = cursor.fetchall()
            cursor.close()
            conn.close()
        except:
            pass
    return hospitals

def get_all_patients():
    conn = get_db_connection()
    patients = []
    if conn:
        try:
            cursor = conn.cursor(dictionary=True)
            # ⬇️ join hata diya, ab patients table se direct hospital_name utha rahe hain
            cursor.execute("""
                SELECT patient_id, name, age, `condition`, hospital_name
                FROM patients
                ORDER BY patient_id DESC
            """)
            patients = cursor.fetchall()
            cursor.close()
            conn.close()
        except:
            pass
    return patients

# ------------------- ROUTES -------------------
@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse("index.html", {
        "request": request,
        "hospitals": [],
        "db_hospitals": get_all_hospitals(),
        "patients": get_all_patients(),
        "message": None
    })

@app.get("/hospitals")
def hospitals_api():
    hospitals = get_all_hospitals()
    return {"hospitals": hospitals}

@app.post("/get_best_route", response_class=HTMLResponse)
def get_best_route(
    request: Request,
    origin: str = Form(...),
    hospitals: List[str] = Form(None)
):
    origin_coord = get_coordinates(origin)
    if not origin_coord:
        return templates.TemplateResponse("index.html", {
            "request": request,
            "error": f"Could not find ambulance location: {origin}",
            "origin": origin,
            "hospitals": hospitals,
            "db_hospitals": get_all_hospitals(),
            "patients": get_all_patients(),
            "message": None
        })

    results, geometries, destinations = [], [], []
    best_eta, best_hospital, best_index = float('inf'), None, -1

    if not hospitals or len(hospitals) == 0:
        nearest = find_nearest_hospitals(origin_coord, radius_km=5, limit=1)
        if nearest:
            hospitals = [nearest[0]["name"]]
            hospitals_coords = [(nearest[0]["lat"], nearest[0]["lon"])]
        else:
            hospitals, hospitals_coords = [], []
    else:
        hospitals_coords = [get_coordinates(h) for h in hospitals]

    for i, (hospital, dest_coord) in enumerate(zip(hospitals, hospitals_coords)):
        if not dest_coord:
            results.append((hospital, " Location not found"))
            geometries.append(None)
            destinations.append(None)
            continue

        eta, geometry = get_eta_and_geometry(origin_coord, dest_coord)
        if eta == float("inf"):
            results.append((hospital, " Routing failed"))
            geometries.append(None)
            destinations.append(dest_coord)
            continue

        eta_min = round(eta / 60, 1)
        results.append((hospital, f"{eta_min} min"))
        geometries.append(geometry)
        destinations.append(dest_coord)

        if eta < best_eta:
            best_eta, best_hospital, best_index = eta, hospital, i

    return templates.TemplateResponse("index.html", {
        "request": request,
        "origin": origin,
        "hospitals": hospitals,
        "results": results,
        "best_hospital": best_hospital,
        "best_eta": round(best_eta / 60, 1) if best_eta != float('inf') else None,
        "geometries": geometries,
        "coordinates": {
            "origin": origin_coord,
            "destinations": destinations
        },
        "best_index": best_index,
        "db_hospitals": get_all_hospitals(),
        "patients": get_all_patients(),
        "message": None
    })

@app.get("/download-report")
def download_report(
    hospital_name: str,
    eta: str,
    distance: str = "N/A",
    route: str = "N/A"
):
    file_name = "route_report.pdf"
    c = canvas.Canvas(file_name, pagesize=A4)
    width, height = A4

    c.setFont("Helvetica-Bold", 18)
    c.drawCentredString(width / 2, height - 100, "🚑 Ambulance Route Report")

    c.setFont("Helvetica", 12)
    c.drawString(100, height - 150, f"🏥 Hospital: {hospital_name}")
    c.drawString(100, height - 170, f"📍 Distance: {distance}")
    c.drawString(100, height - 190, f"⏱ ETA: {eta}")
    c.drawString(100, height - 210, f"🛣 Route: {route}")

    c.setFont("Helvetica-Oblique", 10)
    c.drawString(100, 80, "Generated by Smart Route Ambulance System")
    c.save()

    return FileResponse(path=file_name, filename=file_name, media_type="application/pdf")

@app.post("/add_patient")
def add_patient(
    name: str = Form(...),
    age: int = Form(...),
    condition: str = Form(...),
    hospital_name: str = Form(...)
):
    conn = get_db_connection()
    if not conn:
        return JSONResponse(content={
            "status": "error",
            "message": "❌ Database connection failed"
        }, status_code=500)

    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO patients (name, age, `condition`, hospital_name)
            VALUES (%s, %s, %s, %s)
        """, (name, age, condition, hospital_name))
        conn.commit()
        cursor.close()
        conn.close()
        return JSONResponse(content={
            "status": "success",
            "message": "Patient added successfully"
        })
    except Error as e:
        return JSONResponse(content={
            "status": "error",
            "message": f"Error: {str(e)}"
        }, status_code=500)

# ------------------- 🔹 HOSPITAL CATEGORY FEATURE -------------------
@app.get("/get_hospitals_by_disease")
def get_hospitals_by_disease(disease: str):
    conn = get_db_connection()
    if not conn:
        return JSONResponse(content={"status": "error", "message": "DB connection failed"}, status_code=500)

    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT hospital_name FROM hospitals_category WHERE disease = %s
        """, (disease,))
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        hospitals = [row["hospital_name"] for row in rows]
        return {"status": "success", "hospitals": hospitals}
    except Error as e:
        return JSONResponse(content={"status": "error", "message": str(e)}, status_code=500)
    
# ------------------- 🤖 AI-BASED HOSPITAL RECOMMENDATION -------------------
@app.post("/recommend_hospital")
def recommend_hospital(
    name: str = Form(...),
    age: int = Form(...),
    disease: str = Form(...),
    condition: str = Form(...)
):
    """
    Simple rule-based hospital recommendation system.
    Later you can replace this with ML model.
    """
    recommendation = None

    # Example rule-based logic
    if "heart" in disease.lower():
        if int(age) > 60 or "critical" in condition.lower():
            recommendation = "NICVD - National Institute of Cardiovascular Diseases"
        else:
            recommendation = "Tabba Heart Institute"
    elif "skin" in disease.lower():
        recommendation = "Regal Skin Hospital"
    elif "cancer" in disease.lower():
        recommendation = "Shaukat Khanum Memorial Cancer Hospital"
    elif "children" in disease.lower() or "child" in disease.lower():
        recommendation = "Agha Khan Children's Hospital"
    else:
        recommendation = "Civil Hospital Karachi"

    return JSONResponse(content={
        "status": "success",
        "patient": {
            "name": name,
            "age": age,
            "disease": disease,
            "condition": condition
        },
        "recommended_hospital": recommendation
    })
 
