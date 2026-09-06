const tokenInput = document.getElementById("token");
const authSection = document.getElementById("auth");
const authError = document.getElementById("auth-error");
const appsEl = document.getElementById("apps");
const errorEl = document.getElementById("error");
const createName = document.getElementById("create-name");
const createType = document.getElementById("create-type");

tokenInput.value = sessionStorage.getItem("tc002_token") || "";
let colors = {};

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

function showError(error) {
  if (error && error.status === 401) {
    setAuthVisible(true);
    authError.textContent = "Token required";
    return;
  }
  if (errorEl) errorEl.textContent = error ? error.message : "";
}

function colorOptions(selected) {
  const select = document.createElement("select");
  for (const name of Object.keys(colors)) {
    const option = document.createElement("option");
    option.value = name;
    option.textContent = name;
    select.append(option);
  }
  const match = Object.entries(colors).find(([, hex]) => hex === selected);
  select.value = match ? match[0] : "white";
  return select;
}

function readFileDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

function renderApps(apps) {
  appsEl.replaceChildren();
  if (!apps.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "No apps yet. Create a text or image app; it becomes a DIY page on the clock.";
    appsEl.append(empty);
    return;
  }
  for (const app of apps) {
    const row = document.createElement("form");
    row.className = "app";
    const heading = document.createElement("div");
    heading.className = "heading";
    const title = document.createElement("span");
    title.textContent = app.type ? `${app.name} (${app.type})` : app.name;
    const status = document.createElement("span");
    status.className = "status";
    heading.append(title, status);

    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "Delete";
    remove.addEventListener("click", async () => {
      errorEl.textContent = "";
      try {
        await api(`/api/apps/${app.name}`, { method: "DELETE" });
        await load();
      } catch (error) {
        showError(error);
      }
    });

    row.append(heading, remove);
    if (app.type === "text") {
      status.textContent = app.error ? "error: " + app.error : (app.text == null ? "(empty)" : app.text);
      const text = document.createElement("input");
      text.type = "text";
      text.name = "text";
      text.maxLength = 256;
      text.value = app.text || "";
      text.placeholder = "Message";
      const color = colorOptions(app.color);
      const ansiLabel = document.createElement("label");
      const ansi = document.createElement("input");
      ansi.type = "checkbox";
      ansi.checked = Boolean(app.ansi);
      ansiLabel.append(ansi, document.createTextNode(" ANSI"));
      const send = document.createElement("button");
      send.textContent = "Send";
      row.addEventListener("submit", async (event) => {
        event.preventDefault();
        errorEl.textContent = "";
        try {
          await api(`/api/apps/${app.name}`, {
            method: "POST",
            body: JSON.stringify({ text: text.value, color: color.value, ansi: ansi.checked }),
          });
          await load();
        } catch (error) {
          showError(error);
        }
      });
      row.append(text, color, ansiLabel, send);
    } else if (app.type === "image") {
      status.textContent = app.error ? "error: " + app.error : (app.image ? "image set" : "(empty)");
      const preview = document.createElement("img");
      preview.className = "preview";
      preview.alt = "";
      if (app.image) preview.src = app.image;
      else preview.hidden = true;
      const file = document.createElement("input");
      file.type = "file";
      file.accept = "image/gif,image/png,.gif,.png";
      const send = document.createElement("button");
      send.textContent = "Send";
      row.addEventListener("submit", async (event) => {
        event.preventDefault();
        errorEl.textContent = "";
        if (!file.files[0]) {
          errorEl.textContent = "Choose a GIF or PNG";
          return;
        }
        try {
          const image = await readFileDataUrl(file.files[0]);
          await api(`/api/apps/${app.name}`, {
            method: "POST",
            body: JSON.stringify({ image }),
          });
          await load();
        } catch (error) {
          showError(error);
        }
      });
      row.append(preview, file, send);
    } else {
      status.textContent = "on device";
    }
    appsEl.append(row);
  }
}

document.getElementById("save-token").addEventListener("click", () => {
  sessionStorage.setItem("tc002_token", tokenInput.value);
  authError.textContent = "";
  load();
});

document.getElementById("create-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  errorEl.textContent = "";
  try {
    await api("/api/apps", {
      method: "POST",
      body: JSON.stringify({ name: createName.value, type: createType.value }),
    });
    createName.value = "";
    await load();
  } catch (error) {
    showError(error);
  }
});

async function load() {
  try {
    const [apps, palette] = await Promise.all([api("/api/apps"), api("/api/colors")]);
    setAuthVisible(false);
    authError.textContent = "";
    errorEl.textContent = "";
    colors = palette;
    renderApps(apps);
  } catch (error) {
    showError(error);
  }
}

load();
