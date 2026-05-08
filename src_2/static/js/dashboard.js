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

    const latestTimestamp = data[data.length - 1].timestamp;
    if (latestTimestamp === lastDataCount[activeSensor]) return;
    lastDataCount[activeSensor] = latestTimestamp;

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

let currentSensorConfig = null;

async function loadSensorConfig() {
    try {
        const res = await fetch('/api/sensors/config');
        currentSensorConfig = await res.json();
        renderSensorConfig();
    } catch (e) {
        console.error('Failed to load sensor config:', e);
        const container = document.getElementById('sensor-config-container');
        if (container) container.innerHTML = '<div style="color: var(--accent);">Error loading config</div>';
    }
}

function renderSensorConfig() {
    const container = document.getElementById('sensor-config-container');
    if (!container || !currentSensorConfig) return;

    let html = `
        <div style="display: flex; flex-direction: column; gap: 0.5rem; background: rgba(0,0,0,0.2); padding: 1rem; border-radius: 12px;">
            <label style="color: var(--primary); font-size: 0.9rem;">Background Audio</label>
            <input type="text" id="cfg-bg-audio" value="${currentSensorConfig.background_audio || ''}" style="padding: 0.5rem; border-radius: 6px; border: 1px solid rgba(255,255,255,0.1); background: rgba(0,0,0,0.5); color: white; font-family: inherit;">
        </div>
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem;">
    `;

    for (let i = 1; i <= 8; i++) {
        const colId = `ESP_COLUMN_${i}`;
        const data = currentSensorConfig.sensors ? currentSensorConfig.sensors[colId] || {} : {};
        html += `
            <div style="background: rgba(0,0,0,0.2); padding: 1rem; border-radius: 12px; display: flex; flex-direction: column; gap: 0.5rem;">
                <h3 style="margin: 0; font-size: 1rem; color: var(--text);">${colId}</h3>
                
                <label style="color: #888; font-size: 0.8rem; margin-top: 0.5rem;">Audio File</label>
                <input type="text" id="cfg-audio-${colId}" value="${data.audio_file || ''}" style="padding: 0.5rem; border-radius: 6px; border: 1px solid rgba(255,255,255,0.1); background: rgba(0,0,0,0.5); color: white; font-family: inherit;">
                
                <label style="color: #888; font-size: 0.8rem; margin-top: 0.5rem;">Min Distance (cm)</label>
                <input type="number" step="0.1" id="cfg-dist-${colId}" value="${data.min_distance || 40.0}" style="padding: 0.5rem; border-radius: 6px; border: 1px solid rgba(255,255,255,0.1); background: rgba(0,0,0,0.5); color: white; font-family: inherit;">
            </div>
        `;
    }
    html += `</div>`;
    container.innerHTML = html;
}

async function saveSensorConfig() {
    if (!currentSensorConfig) return;

    const btn = document.querySelector('button[onclick="saveSensorConfig()"]');
    if (btn) {
        btn.textContent = 'Saving...';
        btn.disabled = true;
    }

    currentSensorConfig.background_audio = document.getElementById('cfg-bg-audio').value;
    if (!currentSensorConfig.sensors) currentSensorConfig.sensors = {};
    
    for (let i = 1; i <= 8; i++) {
        const colId = `ESP_COLUMN_${i}`;
        if (!currentSensorConfig.sensors[colId]) currentSensorConfig.sensors[colId] = {};
        currentSensorConfig.sensors[colId].audio_file = document.getElementById(`cfg-audio-${colId}`).value;
        currentSensorConfig.sensors[colId].min_distance = parseFloat(document.getElementById(`cfg-dist-${colId}`).value);
    }

    try {
        const res = await fetch('/api/sensors/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(currentSensorConfig)
        });
        const result = await res.json();
        if (result.status === 'success') {
            if (btn) {
                btn.textContent = 'Saved!';
                btn.style.background = 'var(--success)';
                setTimeout(() => {
                    btn.textContent = 'Save Configuration';
                    btn.style.background = '';
                    btn.disabled = false;
                }, 2000);
            }
        } else {
            throw new Error(result.message);
        }
    } catch (e) {
        console.error('Save failed:', e);
        if (btn) {
            btn.textContent = 'Error';
            btn.style.background = 'var(--accent)';
            setTimeout(() => {
                btn.textContent = 'Save Configuration';
                btn.style.background = '';
                btn.disabled = false;
            }, 2000);
        }
    }
}

async function init() {
  await fetchStatus();
  await loadSensorConfig();
}

init();
setInterval(fetchStatus, 2000);
setInterval(fetchData, 400);
