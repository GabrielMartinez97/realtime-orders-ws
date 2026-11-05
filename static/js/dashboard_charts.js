/**
 * Controlador de KPIs y gráficos en vivo con Chart.js (Fase 6).
 * Paleta inspirada en el Figma UI Kit Order.uk (#FC8A06 Orange, #028643 Green, #03081F Navy).
 */

const STATUS_ORDER = ["RECEIVED", "PREPARING", "READY", "DELIVERED", "CANCELLED"];
const STATUS_LABELS_ES = [
  "Recibido",
  "En cocina",
  "Listo",
  "Entregado",
  "Cancelado",
];

const STATUS_BG_COLORS = [
  "#FC8A06", // RECEIVED (Order.uk Orange)
  "#03081F", // PREPARING (Order.uk Deep Navy)
  "#028643", // READY (Order.uk Basket Green)
  "#64748B", // DELIVERED (Slate)
  "#DC2626", // CANCELLED (Red)
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

  const fontFamily = '"Poppins", system-ui, -apple-system, sans-serif';
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
            borderColor: "#FFFFFF",
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
              color: "#03081F",
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
            backgroundColor: "#FC8A06",
            borderRadius: 8,
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
              color: "#03081F",
              font: { family: fontFamily, size: 12 },
            },
            grid: {
              display: false,
            },
          },
          y: {
            beginAtZero: true,
            ticks: {
              color: "#525866",
              font: { family: monoFamily, size: 11 },
              callback: (val) => `$${val}`,
            },
            grid: {
              color: "rgba(3, 8, 31, 0.08)",
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
