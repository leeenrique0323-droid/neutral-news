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
  };
})();
