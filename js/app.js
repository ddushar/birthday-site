const API = "http://localhost:5000/api";

// Регистрация
async function register() {
  const username = document.getElementById("regUser").value;
  const password = document.getElementById("regPass").value;

  await fetch(`${API}/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password })
  });

  alert("Аккаунт создан!");
}

// Логин
async function login() {
  const username = document.getElementById("logUser").value;
  const password = document.getElementById("logPass").value;

  const res = await fetch(`${API}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password })
  });

  const data = await res.json();
  localStorage.setItem("token", data.token);
  alert("Вход выполнен");
}

// Получение серверов
async function loadServers() {
  const res = await fetch(`${API}/servers`);
  const servers = await res.json();

  const container = document.getElementById("servers");
  servers.forEach(s => {
    container.innerHTML += `
      <div class="card">
        <h3>${s.name}</h3>
        <p>Онлайн: ${s.online}</p>
      </div>
    `;
  });
}
