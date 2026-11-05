/**
 * Controlador de KPIs y gráficos en vivo con Chart.js (Fase 6).
 * Paleta gastronómica cálida (Brasa & Masa — tasteskill 2.5 place deal).
 */

const STATUS_ORDER = ["RECEIVED", "PREPARING", "READY", "DELIVERED", "CANCELLED"];
const STATUS_LABELS_ES = [
  "Recibido",
  "En cocina",
  "Listo",
  "Entregado",
  "Cancelado",
];

// Colores gastronómicos cálidos (terracota, horno ámbar, albahaca, cacao y carmín)
const STATUS_BG_COLORS = [
  "#c84628", // RECEIVED (Terracota Brasa)
  "#d97706", // PREPARING (Ámbar Horno)
  "#2d6a4f", // READY (Verde Albahaca)
  "#6e645c", // DELIVERED (Cacao Piedra)
  "#991b1b", // CANCELLED (Carmín)
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

  const fontFamily = '"Figtree", system-ui, -apple-system, sans-serif';
  const monoFamily = '"JetBrains Mono", monospace';

  if (!statusChartInstance) {
    statusChartInstance = new window.Chart(statusCanvas, {
      type: "doughnut",
      data: {
        labels: STATUS_LABELS_ES,
        datasets: [
          {
            label: "Órdenes",
            data: [0, 0, 0, 0, 0],
            backgroundColor: STATUS_BG_COLORS,
            borderColor: "#ede5d6",
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
              color: "#261b15",
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
            backgroundColor: "#c84628",
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
              color: "#261b15",
              font: { family: fontFamily, size: 12 },
            },
            grid: {
              display: false,
            },
          },
          y: {
            beginAtZero: true,
            ticks: {
              color: "#6e645c",
              font: { family: monoFamily, size: 11 },
              callback: (val) => `$${val}`,
            },
            grid: {
              color: "rgba(38, 27, 21, 0.1)",
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
        : "Global · Todas las sucursales";
  }

  if (!ensureChartsInitialized()) {
    return;
  }

  const byStatus = metrics.orders_by_status || {};
  statusChartInstance.data.datasets[0].data = STATUS_ORDER.map(
    (st) => Number(byStatus[st] || 0)
  );
  statusChartInstance.update();

  const storeItems = metrics.sales_by_store || [];
  storeSalesChartInstance.data.labels = storeItems.map((item) => item.store_name);
  storeSalesChartInstance.data.datasets[0].data = storeItems.map((item) =>
    Number(item.today_sales_total || 0)
  );
  storeSalesChartInstance.update();
}
