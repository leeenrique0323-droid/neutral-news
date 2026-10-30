// 吉祥物「小聞」(mascot) — presentation only; never touches news data.
// Alert state = any pinned 快訊 (`"pinned": true` on a 快訊・初步資訊 item) or an unfinished `ongoing` disaster.
// In alert state the header avatar is hidden and the footer block switches to the 嚴肅 (serious) expression.
(function(){
  const NN = window.NN = window.NN || {};
  const isAlert = i => (i.pinned === true && String(i.status || "").startsWith("快訊")) || !!(i.ongoing && !i.ongoing.ended);
  NN.mascotAlert = items => (items || []).some(isAlert);
  NN.mascot = function(items){
    const alert = NN.mascotAlert(items);
    document.body.dataset.mascot = alert ? "alert" : "normal";
    const base = "assets/mascot/" + (alert ? "xiaowen-serious" : "xiaowen");
    const src = document.getElementById("mascot-src"), img = document.getElementById("mascot-img");
    if(src) src.srcset = `${base}-128.webp 1x, ${base}-256.webp 2x`;
    if(img){ img.srcset = `${base}-128.png 1x, ${base}-256.png 2x`; img.src = `${base}-128.png`; }
    NN.mascotHeadFun();
  };
  // 彩蛋：右上角主播台小聞平常是溫和表情，滑鼠移上去（手機點一下）才換成＞＜開心臉。
  // 有快訊／進行中災害時整個主播台小聞已被隱藏，所以不會在壞消息旁邊出現開心臉。
  NN.mascotHeadFun = function(){
    document.querySelectorAll(".mascot-head,.mascot-side").forEach(el => {
      if(el.dataset.fun) return;
      el.dataset.fun = "1";
      const src = el.querySelector("source"), img = el.querySelector("img");
      const lg = el.dataset.size === "lg";
      const set = b => {
        const one = lg ? `${b}-2x` : `${b}-1x`, two = lg ? `${b}-lg` : `${b}-2x`;
        src.srcset = `assets/mascot/${one}.webp 1x, assets/mascot/${two}.webp 2x`;
        img.srcset = `assets/mascot/${one}.png 1x, assets/mascot/${two}.png 2x`;
        img.src = `assets/mascot/${one}.png`;
      };
      let on = false;
      const fun = v => { if(v === on) return; on = v; set(v ? "xiaowen-desk-happy2" : "xiaowen-desk"); };
      el.addEventListener("mouseenter", () => fun(true));
      el.addEventListener("mouseleave", () => fun(false));
      el.addEventListener("click", () => { fun(!on); if(on) setTimeout(() => fun(false), 1500); });
    });
  };
})();
