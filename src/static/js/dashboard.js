let sensors = [];
let activeSensor = "ESP_COLUMN_1";
let charts = {};
let lastDataCount = 0;

async function fetchStatus() {
  try {
    const response = await fetch("/api/status");
    const status = await response.json();

    const statusEl = document.getElementById("status-text");

    if (statusEl) {
      if (status.serial_connected) {
        statusEl.innerHTML = `<div class="pulse"></div> Live: ${status.sensors.join(", ") || "No sensors"}`;
      } else {
        statusEl.innerHTML = `<div class="pulse disconnected"></div> Waiting for data...`;
      }
    }

    if (status.sensors && status.sensors.length > 0) {
      sensors = status.sensors;
      if (!sensors.includes(activeSensor)) {
        activeSensor = sensors[0];
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
    const colors = ["#00d2ff", "#ff007a", "#3a7bd5", "#4caf50", "#ff9800"];
    const color = colors[sensors.indexOf(sensorId) % colors.length];
    charts[sensorId] = createChart("liveChart", sensorId, color);
  }
}

async function fetchData() {
  try {
    console.log(`Active sensor is ${activeSensor}`);
    const response = await fetch(`/api/readings/${activeSensor}`);
    const data = await response.json();

    if (!data || data.length === 0) return;

    if (data.length === lastDataCount) return;
    lastDataCount = data.length;

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
  if (sensors.length > 0) {
    activeSensor = sensors[0];
    ensureChart(activeSensor);
  } else {
    createChart("liveChart", "Distance (cm)", "#00d2ff");
  }
}

init();
setInterval(fetchStatus, 2000);
setInterval(fetchData, 400);
