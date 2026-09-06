const tokenInput = document.getElementById("token");
const authSection = document.getElementById("auth");
const authError = document.getElementById("auth-error");
const appsEl = document.getElementById("apps");
const textStatus = document.getElementById("text-status");
const textError = document.getElementById("text-error");
const colorSelect = document.getElementById("color");

tokenInput.value = sessionStorage.getItem("tc002_token") || "";

async function api(path, options = {}) {
  const token = sessionStorage.getItem("tc002_token") || "";
  const headers = { ...(options.headers || {}) };
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  if (token) headers.Authorization = "Bearer " + token;
  const response = await fetch(path, { ...options, headers });
  const body = await response.json().catch(() => ({}));
  if (response.status === 401) {
    const error = new Error("Unauthorized");
    error.status = 401;
    throw error;
  }
  if (!response.ok) {
    const detail = body.error || body.detail || response.statusText;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return body;
}

function setAuthVisible(visible) {
  authSection.hidden = !visible;
}

document.getElementById("save-token").addEventListener("click", () => {
  sessionStorage.setItem("tc002_token", tokenInput.value);
  authError.textContent = "";
  load();
});

document.getElementById("text-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  textError.textContent = "";
  try {
    await api("/api/apps/text", {
      method: "POST",
      body: JSON.stringify({
        text: document.getElementById("text").value,
        color: colorSelect.value || "white",
        ansi: document.getElementById("ansi").checked,
      }),
    });
    await load();
  } catch (error) {
    if (error.status === 401) setAuthVisible(true);
    textError.textContent = error.message;
  }
});

function renderApps(apps) {
  appsEl.replaceChildren();
  for (const app of apps) {
    const row = document.createElement("div");
    row.className = "app";
    const name = document.createElement("span");
    name.textContent = app.title || app.name;
    const toggle = document.createElement("input");
    toggle.type = "checkbox";
    toggle.checked = app.enabled;
    toggle.addEventListener("change", async () => {
      try {
        const action = toggle.checked ? "enable" : "disable";
        await api(`/api/apps/${app.name}/${action}`, { method: "POST", body: "{}" });
        await load();
      } catch (error) {
        toggle.checked = app.enabled;
        if (error.status === 401) setAuthVisible(true);
        textError.textContent = error.message;
      }
    });
    row.append(name, toggle, document.createTextNode(app.enabled ? "on" : "off"));
    appsEl.append(row);
  }
}

async function load() {
  try {
    const [apps, colors, text] = await Promise.all([
      api("/api/apps"),
      api("/api/colors"),
      api("/api/apps/text"),
    ]);
    setAuthVisible(false);
    authError.textContent = "";
    if (!colorSelect.options.length) {
      for (const name of Object.keys(colors)) {
        const option = document.createElement("option");
        option.value = name;
        option.textContent = name;
        colorSelect.append(option);
      }
      colorSelect.value = "white";
    }
    renderApps(apps);
    const current = text.text == null ? "(empty)" : text.text;
    textStatus.textContent = text.enabled
      ? `${current} ${text.color || ""} ${text.error ? "error: " + text.error : ""}`
      : "disabled";
  } catch (error) {
    if (error.status === 401) {
      setAuthVisible(true);
      authError.textContent = "Token required";
      return;
    }
    textError.textContent = error.message;
  }
}

load();
