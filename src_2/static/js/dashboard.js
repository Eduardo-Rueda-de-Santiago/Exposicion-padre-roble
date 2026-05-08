let sensors = [];
let activeSensor = null;
let charts = {};
let lastDataCount = {};

async function fetchStatus() {
  try {
    const response = await fetch("/api/status");
    const status = await response.json();

    const statusEl = document.getElementById("status-text");

    if (statusEl) {
      if (status.serial_connected) {
        statusEl.innerHTML = `<div class="pulse"></div> Live: ${status.sensors.length} sensors connected`;
      } else {
        statusEl.innerHTML = `<div class="pulse disconnected"></div> Waiting for data...`;
      }
    }

    if (status.sensors && status.sensors.length > 0) {
      const newSensors = status.sensors.sort();
      if (JSON.stringify(sensors) !== JSON.stringify(newSensors)) {
        sensors = newSensors;
        updateSensorSelector();
      }
      
      if (!activeSensor && sensors.length > 0) {
        setActiveSensor(sensors[0]);
      }
    }

    if (statusEl && status.last_reading_time) {
      const lastTime = new Date(status.last_reading_time).toLocaleTimeString();
      const countEl = document.getElementById("readings-count");
      if (countEl) {
        countEl.textContent = `${status.readings_count} readings | Last: ${lastTime}`;
      }
    }
  } catch (err) {
    console.error("Failed to fetch status:", err);
  }
}

function updateSensorSelector() {
    const container = document.getElementById('sensor-selector');
    if (!container) return;
    
    container.innerHTML = '';
    sensors.forEach(sensor => {
        const btn = document.createElement('button');
        // Keep the styling simple and consistent
        btn.className = `btn ${sensor === activeSensor ? 'btn-primary' : ''}`;
        if (sensor !== activeSensor) {
            btn.style.background = 'rgba(255,255,255,0.05)';
        } else {
            btn.style.padding = '0.5rem 1rem';
            btn.style.fontSize = '0.85rem';
        }
        btn.textContent = sensor;
        btn.onclick = () => setActiveSensor(sensor);
        container.appendChild(btn);
    });
}

function setActiveSensor(sensorId) {
    activeSensor = sensorId;
    updateSensorSelector();
    
    // Hide all canvases
    const container = document.getElementById('charts-container');
    if (container) {
        Array.from(container.children).forEach(canvas => {
            canvas.style.display = 'none';
        });
    }
    
    ensureChart(sensorId);
    const canvas = document.getElementById(`chart-${sensorId}`);
    if (canvas) {
        canvas.style.display = 'block';
    }
    
    fetchData();
}

function createChart(canvasId, label, color) {
  const ctx = document.getElementById(canvasId).getContext("2d");
  const gradient = ctx.createLinearGradient(0, 0, 0, 400);
  gradient.addColorStop(0, color.replace("1)", "0.3)"));
  gradient.addColorStop(1, color.replace("1)", "0)"));

  return new Chart(ctx, {
    type: "line",
    data: {
      labels: [],
      datasets: [
        {
          label: label,
          data: [],
          borderColor: color,
          borderWidth: 3,
          pointBackgroundColor: color,
          pointBorderColor: "rgba(255,255,255,0.5)",
          pointHoverRadius: 6,
          pointRadius: 0,
          tension: 0.4,
          fill: true,
          backgroundColor: gradient,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: {
          grid: { display: false },
          ticks: {
            color: "rgba(255,255,255,0.5)",
            font: { family: "Outfit", size: 10 },
            maxRotation: 0,
          },
        },
        y: {
          grid: { color: "rgba(255,255,255,0.05)" },
          ticks: {
            color: "rgba(255,255,255,0.5)",
            font: { family: "Outfit", size: 12 },
          },
          suggestedMin: 0,
          suggestedMax: 100,
        },
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: "rgba(0,0,0,0.8)",
          titleFont: { family: "Outfit" },
          bodyFont: { family: "Outfit" },
          padding: 12,
          cornerRadius: 8,
        },
      },
      animation: { duration: 400, easing: "easeOutQuart" },
    },
  });
}

function ensureChart(sensorId) {
  if (!charts[sensorId]) {
    const container = document.getElementById('charts-container');
    if (!container) return;
    
    const canvas = document.createElement('canvas');
    canvas.id = `chart-${sensorId}`;
    canvas.style.display = 'none';
    container.appendChild(canvas);
    
    const colors = ["#00d2ff", "#ff007a", "#3a7bd5", "#4caf50", "#ff9800"];
    const color = colors[sensors.indexOf(sensorId) % colors.length];
    charts[sensorId] = createChart(canvas.id, sensorId, color);
  }
}

async function fetchData() {
  if (!activeSensor) return;
  
  try {
    const response = await fetch(`/api/readings/${activeSensor}`);
    const data = await response.json();

    if (!data || data.length === 0) return;

    if (data.length === lastDataCount[activeSensor]) return;
    lastDataCount[activeSensor] = data.length;

    ensureChart(activeSensor);
    const chart = charts[activeSensor];

    chart.data.labels = data.map((r) => {
      const date = new Date(r.timestamp);
      return date.toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      });
    });

    chart.data.datasets[0].data = data.map((r) => r.value);
    chart.update("none");
  } catch (err) {
    console.error("Failed to sync with sensor:", err);
  }
}

async function init() {
  await fetchStatus();
}

init();
setInterval(fetchStatus, 2000);
setInterval(fetchData, 400);
