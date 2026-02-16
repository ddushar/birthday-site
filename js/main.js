// Онлайн счётчик
let online = document.getElementById("online");
if (online) {
  let target = 8421;
  let count = 0;

  let interval = setInterval(() => {
    count += 120;
    if (count >= target) {
      count = target;
      clearInterval(interval);
    }
    online.innerText = count;
  }, 20);
}

// Фейковый API серверов
let serversContainer = document.getElementById("servers");
if (serversContainer) {
  let servers = [
    { name: "Downtown", online: 1200 },
    { name: "Vinewood", online: 980 },
    { name: "Ocean", online: 750 },
  ];

  servers.forEach(server => {
    let div = document.createElement("div");
    div.className = "card";
    div.innerHTML = `
      <h3>${server.name}</h3>
      <p>Онлайн: ${server.online}</p>
    `;
    serversContainer.appendChild(div);
  });
}

// Модалка
function openModal() {
  document.getElementById("modal").style.display = "flex";
}

function closeModal() {
  document.getElementById("modal").style.display = "none";
}

// Тема
function toggleTheme() {
  document.body.classList.toggle("light");
}
