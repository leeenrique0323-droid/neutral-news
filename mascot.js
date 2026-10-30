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
  // 彩蛋：標題旁小頭像平常是溫和表情，滑鼠移上去（手機點一下）才換成＞＜開心臉。
  // 有快訊／進行中災害時整個小頭像已被隱藏，所以不會在壞消息旁邊出現開心臉。
  NN.mascotHeadFun = function(){
    const head = document.querySelector(".mascot-head");
    if(!head || head.dataset.fun) return;
    head.dataset.fun = "1";
    const src = head.querySelector("source"), img = head.querySelector("img");
    const set = b => {
      src.srcset = `assets/mascot/${b}-128.webp 1x, assets/mascot/${b}-256.webp 2x`;
      img.srcset = `assets/mascot/${b}-128.png 1x, assets/mascot/${b}-256.png 2x`;
      img.src = `assets/mascot/${b}-128.png`;
    };
    let on = false;
    const fun = v => { if(v === on) return; on = v; set(v ? "xiaowen-happy2" : "xiaowen"); };
    head.addEventListener("mouseenter", () => fun(true));
    head.addEventListener("mouseleave", () => fun(false));
    head.addEventListener("click", () => { fun(!on); if(on) setTimeout(() => fun(false), 1500); });
  };
})();
