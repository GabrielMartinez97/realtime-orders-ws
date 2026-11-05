/**
 * Controlador de KPIs y gráficos en vivo con Chart.js (Fase 6).
 * Actualiza los datasets en memoria (chart.update()) sin recargar la página ni recrear el canvas.
 */

const STATUS_ORDER = ["RECEIVED", "PREPARING", "READY", "DELIVERED", "CANCELLED"];
const STATUS_LABELS_ES = [
  "Recibido",
  "Preparando",
  "Listo",
  "Entregado",
  "Cancelado",
];

// Colores sobrios alineados con la paleta stone-blueprint (tasteskill 2.5)
const STATUS_BG_COLORS = [
  "#2456d6", // RECEIVED (Blueprint Cobalt)
  "#b4690e", // PREPARING (Warm Amber)
  "#0f7647", // READY (Forest Green)
  "#5a5850", // DELIVERED (Stone Muted Charcoal)
  "#8f1d18", // CANCELLED (Brick Crimson)
];

let statusChartInstance = null;
let storeSalesChartInstance = null;

function ensureChartsInitialized() {
  if (typeof window.Chart === "undefined") {
    return false;
  }

  const statusCanvas = document.getElementById("chart-orders-status");
  const salesCanvas = document.getElementById("chart-store-sales");
  if (!statusCanvas || !salesCanvas) {
    return false;
  }

  const fontFamily = '"Host Grotesk", system-ui, -apple-system, sans-serif';
  const monoFamily = '"JetBrains Mono", monospace';

  if (!statusChartInstance) {
    statusChartInstance = new window.Chart(statusCanvas, {
      type: "doughnut",
      data: {
        labels: STATUS_LABELS_ES,
        datasets: [
          {
            label: "Pedidos",
            data: [0, 0, 0, 0, 0],
            backgroundColor: STATUS_BG_COLORS,
            borderColor: "#ecebe7",
            borderWidth: 2,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: "62%",
        plugins: {
          legend: {
            position: "bottom",
            labels: {
              color: "#26251e",
              font: { family: fontFamily, size: 12 },
              boxWidth: 12,
              padding: 12,
            },
          },
        },
      },
    });
  }

  if (!storeSalesChartInstance) {
    storeSalesChartInstance = new window.Chart(salesCanvas, {
      type: "bar",
      data: {
        labels: [],
        datasets: [
          {
            label: "Ventas hoy ($)",
            data: [],
            backgroundColor: "#2456d6",
            borderRadius: 6,
            maxBarThickness: 44,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            display: false,
          },
        },
        scales: {
          x: {
            ticks: {
              color: "#26251e",
              font: { family: fontFamily, size: 12 },
            },
            grid: {
              display: false,
            },
          },
          y: {
            beginAtZero: true,
            ticks: {
              color: "#5a5850",
              font: { family: monoFamily, size: 11 },
              callback: (val) => `$${val}`,
            },
            grid: {
              color: "rgba(38, 37, 30, 0.1)",
            },
          },
        },
      },
    });
  }

  return true;
}

export function renderDashboardMetrics(metrics) {
  if (!metrics) return;

  const activeEl = document.getElementById("kpi-active-orders");
  const salesEl = document.getElementById("kpi-today-sales");
  const prepEl = document.getElementById("kpi-avg-prep");
  const scopeBadgeEl = document.getElementById("dashboard-scope-badge");

  if (activeEl) {
    activeEl.textContent = String(metrics.active_orders_count ?? 0);
  }
  if (salesEl) {
    const numSales = Number(metrics.today_sales_total ?? 0);
    salesEl.textContent = `$${numSales.toFixed(2)}`;
  }
  if (prepEl) {
    const numPrep = Number(metrics.avg_prep_time_minutes ?? 0);
    prepEl.textContent = `${numPrep.toFixed(1)} min`;
  }
  if (scopeBadgeEl) {
    scopeBadgeEl.textContent =
      metrics.scope === "store" && metrics.store_name
        ? `${metrics.store_name} · En vivo`
        : "Global · Todas las tiendas";
  }

  if (!ensureChartsInitialized()) {
    return;
  }

  // 1. Actualizar gráfico de Pedidos por Estado sin recargar
  const byStatus = metrics.orders_by_status || {};
  statusChartInstance.data.datasets[0].data = STATUS_ORDER.map(
    (st) => Number(byStatus[st] || 0)
  );
  statusChartInstance.update();

  // 2. Actualizar gráfico de Ventas del Día por Sucursal sin recargar
  const storeItems = metrics.sales_by_store || [];
  storeSalesChartInstance.data.labels = storeItems.map((item) => item.store_name);
  storeSalesChartInstance.data.datasets[0].data = storeItems.map((item) =>
    Number(item.today_sales_total || 0)
  );
  storeSalesChartInstance.update();
}
