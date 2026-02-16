let online = document.getElementById("online");

if (online) {
  let count = 0;
  let target = 5421;

  let interval = setInterval(() => {
    count += 100;
    if (count >= target) {
      count = target;
      clearInterval(interval);
    }
    online.innerText = count;
  }, 20);
}
