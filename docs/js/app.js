// Render backend
const API = "https://birthday-site.onrender.com/api";

// Онлайн счётчик
let online = document.getElementById("online");
if(online){
  let target = 8421, count = 0;
  let interval = setInterval(()=>{
    count += 120;
    if(count >= target){count = target; clearInterval(interval);}
    online.innerText = count;
  }, 20);
}

// Модалка
function openModal(){document.getElementById("modal").style.display="flex";}
function closeModal(){document.getElementById("modal").style.display="none";}
