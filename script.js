const map = L.map('map').setView([24.8607, 67.0011], 12); // Default Karachi
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: 'Umer Haroon', maxZoom: 19
}).addTo(map);

let ambulanceMarker = null;

// 🔹 Click to set ambulance location (manual)
map.on('click', function(e) {
    const latlng = e.latlng;
    if (ambulanceMarker) {
        map.removeLayer(ambulanceMarker);
    }
    ambulanceMarker = L.marker(latlng).addTo(map).bindPopup("Ambulance").openPopup();
    document.getElementById('origin').value = `${latlng.lat},${latlng.lng}`;
});

// 🔹 Add hospital input
function addHospitalInput() {
    const container = document.getElementById('hospitalInputs');
    const input = document.createElement('input');
    input.type = "text";
    input.name = "hospitals";
    input.required = true;
    input.placeholder = "Enter hospital location";
    container.appendChild(input);
}

// 🔹 Draw routes if available
if (geoData.origin && geoData.geometries.length > 0) {
    const origin = geoData.origin;
    const dests = geoData.destinations;

    // Origin marker
    L.marker(origin, {
        icon: L.icon({
            iconUrl: 'https://cdn-icons-png.flaticon.com/512/2961/2961948.png',
            iconSize: [30, 30]
        })
    }).addTo(map).bindPopup("Ambulance Location");

    // Dest markers
    dests.forEach((dest, index) => {
        if (!dest) return;
        let popup, iconOptions;
        if (index === geoData.best_index) {
            popup = "Best Hospital (Nearest)";
            iconOptions = { iconUrl: "https://cdn-icons-png.flaticon.com/512/684/684908.png", iconSize: [30, 30] };
        } else {
            popup = "Hospital";
            iconOptions = { iconUrl: "https://cdn-icons-png.flaticon.com/512/854/854878.png", iconSize: [25, 25] };
        }
        L.marker(dest, { icon: L.icon(iconOptions) }).addTo(map).bindPopup(popup);
    });

    // Routes
    geoData.geometries.forEach((geo, i) => {
        if (!geo) return;
        const coords = geo.coordinates.map(([lng, lat]) => [lat, lng]);
        const color = (i === geoData.best_index) ? 'green' : 'gray';
        L.polyline(coords, { color: color, weight: 5, opacity: 0.7 }).addTo(map);
    });

    const bounds = [origin, ...dests.filter(Boolean)];
    map.fitBounds(bounds);
}

// 🔹 Live Ambulance Tracking (Auto GPS update)
function startLiveTracking() {
    if (!navigator.geolocation) {
        alert("Geolocation is not supported by your browser.");
        return;
    }

    navigator.geolocation.watchPosition(
        (pos) => {
            const lat = pos.coords.latitude;
            const lon = pos.coords.longitude;

            // Marker update
            if (ambulanceMarker) {
                ambulanceMarker.setLatLng([lat, lon]);
            } else {
                ambulanceMarker = L.marker([lat, lon], {
                    icon: L.icon({
                        iconUrl: 'https://cdn-icons-png.flaticon.com/512/2961/2961948.png',attribution: 'Umer Haroon', maxZoom: 19, iconSize: [30, 30]
                        
                    })
                }).addTo(map).bindPopup("🚑 Live Ambulance").openPopup();
            }

            // Auto-update hidden input for route calculation
            const originInput = document.getElementById('origin');
            if (originInput) {
                originInput.value = `${lat},${lon}`;
            }

            // Center map on ambulance
            map.setView([lat, lon], 14);
        },
        (err) => {
            console.error("GPS Error:", err);
        },
        { enableHighAccuracy: true }
    );
}
// 🔹 Start live tracking automatically when page loads
window.addEventListener("load", () => {
    startLiveTracking();
});
