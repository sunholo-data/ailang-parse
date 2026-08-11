/**
 * AILANG Parse — Homepage v2 Animations
 * IntersectionObserver-driven scroll animations for visual storytelling sections.
 * No DOM ID conflicts with wasm-demo.js.
 */
(function () {
  'use strict';

  // ── REVEAL OBSERVER (handles .reveal-left, .reveal-right, .reveal-scale) ──
  var revealObs = new IntersectionObserver(function (entries) {
    entries.forEach(function (e) {
      if (e.isIntersecting) e.target.classList.add('visible');
    });
  }, { threshold: 0.12, rootMargin: '0px 0px -30px 0px' });
  document.querySelectorAll('.reveal-left, .reveal-right, .reveal-scale').forEach(function (el) {
    revealObs.observe(el);
  });

  // ── XML TICKER parallax ──
  var ticker = document.getElementById('xml-ticker-inner');
  if (ticker) {
    var xmlSnippet = '<w:body> <w:p> <w:pPr> <w:rPr> <w:b/> </w:rPr> </w:pPr> <w:r> <w:t>Hello</w:t> </w:r> </w:p> <w:tbl> <w:tr> <w:tc> <w:tcPr> <w:gridSpan w:val="2"/> </w:tcPr> </w:tc> </w:tr> </w:tbl> <w:ins w:author="Alice"> <w:r> <w:t>updated</w:t> </w:r> </w:ins> </w:body>   ';
    ticker.textContent = xmlSnippet.repeat(10);
    window.addEventListener('scroll', function () {
      ticker.style.transform = 'translateX(' + (-scrollY * 0.3) + 'px)';
    }, { passive: true });
  }

  // ── XML SIDEBARS (horizontal lines, slow vertical parallax) ──
  var xmlLines = [
    '<w:body>',
    '  <w:p>',
    '    <w:pPr>',
    '      <w:rPr><w:b/></w:rPr>',
    '    </w:pPr>',
    '    <w:r>',
    '      <w:t>Hello</w:t>',
    '    </w:r>',
    '  </w:p>',
    '  <w:tbl>',
    '    <w:tr>',
    '      <w:tc>',
    '        <w:tcPr>',
    '          <w:gridSpan w:val="2"/>',
    '        </w:tcPr>',
    '        <w:p><w:r><w:t>EMEA</w:t></w:r></w:p>',
    '      </w:tc>',
    '    </w:tr>',
    '  </w:tbl>',
    '  <w:ins w:author="Alice">',
    '    <w:r>',
    '      <w:t>net-60 days</w:t>',
    '    </w:r>',
    '  </w:ins>',
    '  <w:del w:author="Bob">',
    '    <w:r>',
    '      <w:t>net-30 days</w:t>',
    '    </w:r>',
    '  </w:del>',
    '  <w:commentRangeStart/>',
    '  <w:p>',
    '    <w:r><w:t>Review this</w:t></w:r>',
    '  </w:p>',
    '  <w:commentRangeEnd/>',
    '  <w:sdt>',
    '    <w:sdtPr>',
    '      <w:tag w:val="header"/>',
    '    </w:sdtPr>',
    '  </w:sdt>',
    '</w:body>'
  ];
  var sidebarL = document.getElementById('xml-sidebar-left-inner');
  var sidebarR = document.getElementById('xml-sidebar-right-inner');
  var sidebarContL = document.getElementById('xml-sidebar-left');
  var sidebarContR = document.getElementById('xml-sidebar-right');
  // Repeat the lines many times to fill the tall scroll area
  var longContent = '';
  for (var r = 0; r < 15; r++) longContent += xmlLines.join('\n') + '\n\n';
  if (sidebarL) sidebarL.textContent = longContent;
  if (sidebarR) sidebarR.textContent = longContent;
  // Show sidebars once past hero, very slow parallax (much slower than page scroll)
  var ticking = false;
  function updateSidebars() {
    var y = window.scrollY;
    var show = y > 200;
    if (sidebarContL) sidebarContL.classList.toggle('visible', show);
    if (sidebarContR) sidebarContR.classList.toggle('visible', show);
    // Very slow: 0.04x and 0.03x scroll speed — they barely move
    if (sidebarL) sidebarL.style.transform = 'translateY(' + (-y * 0.04) + 'px)';
    if (sidebarR) sidebarR.style.transform = 'translateY(' + (-y * 0.03 - 100) + 'px)';
    ticking = false;
  }
  window.addEventListener('scroll', function () {
    if (!ticking) { requestAnimationFrame(updateSidebars); ticking = true; }
  }, { passive: true });

  // ── DOCUMENT DECOMPOSITION ──
  // Show the intact document page first, then after 1.2s delay break it apart
  // and reveal the block chips one by one.
  var docVisual = document.getElementById('vs-doc-visual');
  if (docVisual) {
    var docPage = document.getElementById('vs-doc-page');
    var chips = [];
    for (var i = 0; i < 6; i++) {
      var chip = document.getElementById('vs-chip-' + i);
      if (chip) chips.push(chip);
    }
    var decomposed = false;
    var decompTimer = null;
    new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting && !decomposed) {
          // Wait 1.2s so user sees the pristine page first
          decompTimer = setTimeout(function () {
            decomposed = true;
            if (docPage) docPage.classList.add('breaking');
            chips.forEach(function (c, idx) {
              setTimeout(function () {
                c.classList.add('vis');
              }, idx * 150);
            });
          }, 1200);
        }
        // If user scrolls away before animation fires, cancel it
        if (!e.isIntersecting && !decomposed && decompTimer) {
          clearTimeout(decompTimer);
        }
      });
    }, { threshold: 0.4 }).observe(docVisual);
  }

  // ── TRACK CHANGES ──
  var tcViz = document.getElementById('vs-tc-viz');
  if (tcViz) {
    new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) e.target.classList.add('active');
      });
    }, { threshold: 0.5 }).observe(tcViz);
  }

  // ── MERGED CELLS ──
  var mergeViz = document.getElementById('vs-merge-viz');
  if (mergeViz) {
    new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) {
          var arrow = document.getElementById('vs-merge-arrow');
          if (arrow) arrow.classList.add('vis');
        }
      });
    }, { threshold: 0.4 }).observe(mergeViz);
  }

  // ── BENCHMARK BARS ──
  var benchBars = document.getElementById('vs-bench-bars');
  var benchDone = false;
  if (benchBars) {
    new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting && !benchDone) {
          benchDone = true;
          var fills = benchBars.querySelectorAll('.vs-bench-fill');
          fills.forEach(function (f) { f.style.width = f.dataset.width + '%'; });
        }
      });
    }, { threshold: 0.3 }).observe(benchBars);
  }

  // ── EVAL PIPELINE ──
  var evalLoop = document.getElementById('vs-eval-loop');
  var evalDone = false;
  if (evalLoop) {
    new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting && !evalDone) {
          evalDone = true;
          // Reveal steps, arrows, and result in sequence
          var steps = ['vs-en-0', 'vs-ea-0', 'vs-en-1', 'vs-ea-1', 'vs-en-2', 'vs-ea-2', 'vs-eval-result'];
          steps.forEach(function (id, idx) {
            setTimeout(function () {
              var el = document.getElementById(id);
              if (el) el.classList.add('vis');
            }, idx * 250);
          });
          // Animate score counter after result appears.
          // Pull live value from window.BENCH_DATA (loaded async by bench-data.js).
          // Falls back to the inline data-bench text (e.g. "92.3%") if fetch hasn't completed.
          var scoreEl = document.getElementById('vs-eval-score');
          if (scoreEl) {
            setTimeout(function () {
              var target = 92.3;
              var bd = window.BENCH_DATA;
              if (bd && bd.adapters) {
                var ap = bd.adapters.find(function (a) { return a.id === 'ailang_parse'; });
                if (ap && typeof ap.composite === 'number') target = ap.composite * 100;
              } else {
                var parsed = parseFloat((scoreEl.textContent || '').replace('%', ''));
                if (!isNaN(parsed) && parsed > 0) target = parsed;
              }
              var frame = 0;
              var interval = setInterval(function () {
                frame++;
                var prog = Math.min(1, frame / 60);
                var eased = 1 - Math.pow(1 - prog, 3);
                scoreEl.textContent = (target * eased).toFixed(1) + '%';
                if (frame >= 60) clearInterval(interval);
              }, 33);
            }, steps.length * 250);
          }
        }
      });
    }, { threshold: 0.3 }).observe(evalLoop);
  }

  // ── PRIVACY CARDS ──
  var flowViz = document.getElementById('vs-flow-viz');
  var flowDone = false;
  if (flowViz) {
    new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting && !flowDone) {
          flowDone = true;
          var card1 = document.getElementById('vs-fp-1');
          var card2 = document.getElementById('vs-fp-3');
          setTimeout(function () { if (card1) card1.classList.add('active'); }, 200);
          setTimeout(function () { if (card2) card2.classList.add('active'); }, 500);
        }
      });
    }, { threshold: 0.3 }).observe(flowViz);
  }

  // ── FORMAT PIPELINE ──
  var pipelineViz = document.getElementById('vs-pipeline-viz');
  var pipeDone = false;
  if (pipelineViz) {
    new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting && !pipeDone) {
          pipeDone = true;
          var files = pipelineViz.querySelectorAll('.vs-pipe-file');
          files.forEach(function (f, idx) {
            setTimeout(function () { f.classList.add('vis'); }, idx * 80);
          });
          var blocks = pipelineViz.querySelectorAll('.vs-pipe-block');
          blocks.forEach(function (b, idx) {
            setTimeout(function () { b.classList.add('vis'); }, 600 + idx * 100);
          });
        }
      });
    }, { threshold: 0.3 }).observe(pipelineViz);
  }
})();
