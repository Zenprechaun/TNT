/* Tahoe Neighborhood Table site script, moved out of Claude/index.html.
   Same behavior as before. Each part now checks that its elements exist, so the
   script also runs on inner pages (like the volunteer page) that only have the footer. */
(function(){
  var SITE='https://tahoeneighborhoodtable.com';
  var LINES={
    food:'We believe everyone deserves a seat at the table.',
    warmth:'We believe everyone deserves a warm place to be.',
    housing:'We believe everyone deserves a place to call home.'
  };
  var root=document.documentElement;
  var grid=document.getElementById('need-grid');
  var toggles=[].slice.call(document.querySelectorAll('.need__toggle'));
  var phrases=[].slice.call(document.querySelectorAll('.phrase'));
  var cards=[].slice.call(document.querySelectorAll('.need'));
  var shareText=document.getElementById('share-text');
  var shareStatus=document.getElementById('share-status');
  var reduce=window.matchMedia&&matchMedia('(prefers-reduced-motion: reduce)').matches;
  var active=null;

  function message(){
    var lead=active?LINES[active]:'Nourishing our community. Building hope.';
    return lead+' Join Tahoe Neighborhood Table: '+SITE;
  }
  function beat(id){
    var el=document.getElementById(id); if(!el) return;
    el.classList.remove('beat'); void el.getBoundingClientRect(); el.classList.add('beat');
  }
  function setActive(name){
    active=name;
    if(name){root.setAttribute('data-need',name);if(grid)grid.setAttribute('data-active',name);}
    else{root.removeAttribute('data-need');if(grid)grid.removeAttribute('data-active');}
    toggles.forEach(function(b){b.setAttribute('aria-pressed',String(b.dataset.need===name));});
    phrases.forEach(function(b){b.setAttribute('aria-pressed',String(b.dataset.need===name));});
    if(shareText)shareText.value=message();
    if(shareStatus)shareStatus.textContent='';
    if(name){beat('hero-heart');beat('band-heart');}
  }
  function hint(name,on){
    phrases.forEach(function(b){b.classList.toggle('is-hint',on&&b.dataset.need===name);});
    cards.forEach(function(c){c.classList.toggle('is-hint',on&&c.dataset.need===name);});
  }

  /* Food video: opening the Food card plays the video in a pop-up player. It streams from Dropbox;
     where the video can't load, the player offers the Dropbox page instead. */
  var VIDEO_PAGE='https://www.dropbox.com/scl/fi/erfuniux4vvwatyydqsp8/TahoeCommunityThanksgiving.mp4?rlkey=poo6yihayjsbvc1b3ux1y4gsx&st=yxu4y9l2&dl=0';
  var VIDEO_FILE=VIDEO_PAGE.replace('dl=0','raw=1');
  var player=document.getElementById('player');
  var video=document.getElementById('player-video');
  var fallback=document.getElementById('player-fallback');
  var opener=null;
  function openPlayer(from){
    if(!player) return;
    opener=from||null;
    fallback.hidden=true;video.hidden=false;
    if(video.error||!video.getAttribute('src')){video.src=VIDEO_FILE;}
    if(typeof player.showModal==='function'){player.showModal();}else{player.setAttribute('open','');}
    var p=video.play();
    if(p&&p.catch){p.catch(function(){});}
  }
  function closePlayer(){
    if(typeof player.close==='function'){player.close();}
    else{player.removeAttribute('open');video.pause();}
  }
  if(player){
    player.addEventListener('close',function(){video.pause();if(opener){opener.focus();}});
    player.addEventListener('click',function(e){if(e.target===player){closePlayer();}});
    document.getElementById('player-close').addEventListener('click',closePlayer);
    video.addEventListener('error',function(){video.hidden=true;fallback.hidden=false;});
    video.addEventListener('loadedmetadata',function(){
      if(video.videoWidth&&video.videoHeight){player.style.setProperty('--ratio',(video.videoWidth/video.videoHeight).toFixed(4));}
    });
  }

  toggles.forEach(function(b){
    b.addEventListener('click',function(){
      var n=active===b.dataset.need?null:b.dataset.need;
      setActive(n);
      if(n==='food'){openPlayer(b);}
    });
    b.addEventListener('pointerenter',function(e){if(e.pointerType==='mouse')hint(b.dataset.need,true);});
    b.addEventListener('pointerleave',function(){hint(b.dataset.need,false);});
  });
  phrases.forEach(function(b){
    b.addEventListener('click',function(){
      var n=active===b.dataset.need?null:b.dataset.need;
      setActive(n);
      if(n){
        var card=document.getElementById('need-'+n);
        var r=card.getBoundingClientRect();
        if(r.top<0||r.bottom>innerHeight){card.scrollIntoView({behavior:reduce?'auto':'smooth',block:'center'});}
      }
    });
    b.addEventListener('pointerenter',function(e){if(e.pointerType==='mouse')hint(b.dataset.need,true);});
    b.addEventListener('pointerleave',function(){hint(b.dataset.need,false);});
  });
  if(grid){
    document.addEventListener('keydown',function(e){
      if(e.key==='Escape'&&active&&!(player&&player.open)&&!document.querySelector('dialog[open]'))setActive(null);
    });
  }

  /* Share: the frame refuses the system share sheet, so offer a message to copy. */
  var shareToggle=document.getElementById('share-toggle');
  var sharePanel=document.getElementById('share-panel');
  if(shareToggle&&sharePanel&&shareText){
    shareText.value=message();
    shareToggle.addEventListener('click',function(){
      var open=sharePanel.hidden;
      sharePanel.hidden=!open;
      shareToggle.setAttribute('aria-expanded',String(open));
      shareStatus.textContent='';
      if(open){shareText.value=message();}
    });
    var selectFallback=function(){
      shareText.focus();shareText.select();
      shareStatus.textContent='Press Ctrl+C or ⌘C to copy the selected text.';
    };
    document.getElementById('share-copy').addEventListener('click',function(){
      var text=shareText.value;
      if(navigator.clipboard&&navigator.clipboard.writeText){
        navigator.clipboard.writeText(text).then(function(){shareStatus.textContent='Copied. Paste it anywhere.';},selectFallback);
      }else{selectFallback();}
    });
  }

  /* Email links do nothing in some viewers, so the address can always be copied. */
  var emailLink=document.getElementById('contact-email');
  var emailCopy=document.getElementById('email-copy');
  var emailStatus=document.getElementById('email-status');
  var emailTimer=0;
  if(emailLink&&emailCopy&&emailStatus){
    emailCopy.addEventListener('click',function(){
      function done(){
        emailStatus.className='vh';
        emailStatus.textContent='Email address copied.';
        emailCopy.textContent='Copied';
        clearTimeout(emailTimer);
        emailTimer=setTimeout(function(){emailCopy.textContent='Copy';emailStatus.textContent='';},2200);
      }
      function fail(){
        var range=document.createRange(),sel=getSelection();
        range.selectNodeContents(emailLink);sel.removeAllRanges();sel.addRange(range);
        emailStatus.className='band__email-status';
        emailStatus.textContent='Press Ctrl+C or ⌘C to copy the selected address.';
      }
      if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(emailLink.textContent).then(done,fail);}
      else{fail();}
    });
  }

  /* The scene leans gently toward the pointer and the pine drifts as the page scrolls. */
  var scene=document.getElementById('scene');
  if(scene&&!reduce){
    var tx=0,ty=0,cx=0,cy=0,raf=0;
    var frame=function(){
      cx+=(tx-cx)*.07;cy+=(ty-cy)*.07;
      scene.style.setProperty('--px',cx.toFixed(3));
      scene.style.setProperty('--py',cy.toFixed(3));
      raf=(Math.abs(tx-cx)+Math.abs(ty-cy)>.002)?requestAnimationFrame(frame):0;
    };
    var nudge=function(){if(!raf)raf=requestAnimationFrame(frame);};
    scene.addEventListener('pointermove',function(e){
      if(e.pointerType!=='mouse')return;
      var r=scene.getBoundingClientRect();
      tx=(e.clientX-r.left)/r.width*2-1;ty=(e.clientY-r.top)/r.height*2-1;nudge();
    });
    scene.addEventListener('pointerleave',function(){tx=0;ty=0;nudge();});
    var ticking=false;
    addEventListener('scroll',function(){
      if(ticking)return;ticking=true;
      requestAnimationFrame(function(){
        scene.style.setProperty('--lift',Math.min(scrollY*.05,40).toFixed(1));
        ticking=false;
      });
    },{passive:true});
  }
})();
