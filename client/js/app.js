const API = "https://birthday-site.onrender.com";

// Онлайн счётчик
let online = document.getElementById("online");
if(online){
  let target=8421,count=0;
  let interval=setInterval(()=>{count+=120;if(count>=target){count=target;clearInterval(interval);}online.innerText=count;},20);
}

// Загрузка серверов
let serversContainer=document.getElementById("servers");
if(serversContainer){
  fetch(`${API}/servers`)
    .then(res=>res.json())
    .then(servers=>{
      servers.forEach(s=>{
        let div=document.createElement("div");
        div.className="card";
        div.innerHTML=`<h3>${s.name}</h3><p>Онлайн: ${s.online}</p>`;
        serversContainer.appendChild(div);
      });
    });
}

// Модалка
function openModal(){document.getElementById("modal").style.display="flex";}
function closeModal(){document.getElementById("modal").style.display="none";}

// Тема
function toggleTheme(){document.body.classList.toggle("light");}

// Авторизация
async function register(){
  const username=document.getElementById("regUser").value;
  const password=document.getElementById("regPass").value;
  await fetch(`${API}/auth/register`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({username,password})});
  alert("Аккаунт создан!");
}

async function login(){
  const username=document.getElementById("logUser").value;
  const password=document.getElementById("logPass").value;
  const res=await fetch(`${API}/auth/login`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({username,password})});
  const data=await res.json();
  localStorage.setItem("token",data.token);
  alert("Вход выполнен");
}
