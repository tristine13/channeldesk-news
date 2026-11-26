/* Public reader: reactions, share, saved list, search, tabs, poll. No login, no composer. */
(function () {
    'use strict';
    var $ = function (s, r) { return (r || document).querySelector(s); };
    var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
    var csrf = ($('meta[name="csrf"]') || {}).content || '';
    var HEART = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1-1.1a5.5 5.5 0 0 0-7.8 7.8l1 1.1L12 21.2l7.8-7.7 1-1.1a5.5 5.5 0 0 0 0-7.8z"/></svg>';
    var toastTimer;

    function toast(msg) {
        var t = $('#rd-toast'); if (!t) return;
        t.textContent = msg; t.classList.add('show');
        clearTimeout(toastTimer); toastTimer = setTimeout(function () { t.classList.remove('show'); }, 2200);
    }
    function post(url, data) {
        var fd = new FormData(); fd.append('csrf_token', csrf);
        Object.keys(data || {}).forEach(function (k) { fd.append(k, data[k]); });
        return fetch(url, { method: 'POST', body: fd, credentials: 'same-origin' })
            .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); });
    }
    function esc(s) { var d = document.createElement('div'); d.textContent = s; return d.innerHTML; }

    /* ---------------- saved reading list (localStorage) ---------------- */
    var KEY = 'cd_saved';
    function getSaved() { try { return JSON.parse(localStorage.getItem(KEY)) || []; } catch (e) { return []; } }
    function setSaved(list) { try { localStorage.setItem(KEY, JSON.stringify(list)); } catch (e) { toast('Saving is turned off in this browser.'); } }
    function isSaved(id) { return getSaved().some(function (s) { return String(s.id) === String(id); }); }
    function renderSaved() {
        var list = getSaved();
        $$('[data-saved-count]').forEach(function (c) { c.textContent = list.length; c.hidden = !list.length; });
        $$('[data-saved-list]').forEach(function (box) {
            if (!list.length) { box.innerHTML = '<p class="rd-muted">' + esc(box.dataset.empty || '') + '</p>'; return; }
            box.innerHTML = list.map(function (s) {
                return '<div class="rd-saved-item"><a href="' + esc(s.url) + '">' + esc(s.title) +
                    '</a><button type="button" data-unsave="' + esc(String(s.id)) + '">Remove</button></div>';
            }).join('');
        });
        $$('[data-save]').forEach(function (b) {
            var on = isSaved(b.dataset.id);
            b.classList.toggle('on', on); b.setAttribute('aria-pressed', on);
            var l = $('span', b); if (l) l.textContent = on ? 'Saved' : 'Save';
        });
    }
    function toggleSave(id, title, url) {
        var list = getSaved();
        if (isSaved(id)) { list = list.filter(function (s) { return String(s.id) !== String(id); }); toast('Removed from reading list'); }
        else { list.unshift({ id: id, title: title, url: url }); toast('Saved to your reading list'); }
        setSaved(list); renderSaved();
    }

    var drawer = $('#rd-drawer'), scrim = $('#rd-scrim');
    function drawerOpen(o) {
        drawer.classList.toggle('open', o); drawer.setAttribute('aria-hidden', !o); scrim.hidden = !o;
    }

    /* ---------------- reactions ---------------- */
    function applyReaction(box, d) {
        box.dataset.mine = d.mine || '';
        $$('[data-kind-count]', box).forEach(function (el) { el.textContent = d.counts[el.dataset.kindCount]; });
        $$('[data-kind]', box).forEach(function (b) { b.classList.toggle('on', b.dataset.kind === d.mine); });
        var tot = $('[data-total]', box); if (tot) tot.textContent = d.total;
        var face = $('[data-face]', box);
        if (face) face.innerHTML = HEART;
        var sum = box.closest('[data-card]'); sum = sum && $('[data-sum]', sum);
        if (sum) sum.innerHTML = d.counts.heart > 0 ? '<i class="rd-sum-heart">' + HEART + '</i>' : '';
        var main = $('.rd-react-main', box); if (main) main.classList.toggle('on', !!d.mine);
        var pop = (face && d.mine) ? face : (d.mine ? $('[data-kind="' + d.mine + '"] span', box) : null);
        if (pop) { pop.classList.remove('rd-bounce'); void pop.offsetWidth; pop.classList.add('rd-bounce'); }
    }
    function react(box, kind) {
        post('/news/' + box.dataset.post + '/react', { kind: kind })
            .then(function (d) { applyReaction(box, d); })
            .catch(function () { toast('Could not save your reaction. Try again.'); });
    }

    // long-press on touch opens the picker
    var pressTimer, pressed;
    document.addEventListener('touchstart', function (e) {
        var main = e.target.closest('.rd-react-main'); if (!main) return;
        pressed = false;
        pressTimer = setTimeout(function () { pressed = true; main.parentNode.classList.add('open'); }, 420);
    }, { passive: true });
    ['touchend', 'touchmove', 'touchcancel'].forEach(function (ev) {
        document.addEventListener(ev, function () { clearTimeout(pressTimer); }, { passive: true });
    });

    /* ---------------- share ---------------- */
    function copy(text) {
        if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text);
        return new Promise(function (res, rej) {
            var t = document.createElement('textarea'); t.value = text; t.style.position = 'fixed'; t.style.opacity = '0';
            document.body.appendChild(t); t.select();
            try { document.execCommand('copy') ? res() : rej(); } catch (e) { rej(e); } t.remove();
        });
    }
    function share(box, how) {
        var url = box.dataset.url, title = box.dataset.title;
        if (how === 'copy') copy(url).then(function () { toast('Link copied'); }, function () { toast('Copy failed. Long-press the address bar instead.'); });
        else if (how === 'messenger') {
            var mobile = /Android|iPhone|iPad/i.test(navigator.userAgent);
            window.open(mobile ? 'fb-messenger://share/?link=' + encodeURIComponent(url)
                : 'https://www.facebook.com/sharer/sharer.php?u=' + encodeURIComponent(url), '_blank', 'noopener');
        } else if (how === 'story') {
            // Instagram has no web share link: copy it so it can be pasted as a Story link sticker
            copy(url).then(function () { toast('Link copied. Paste it as a link sticker in your Story.'); },
                function () { toast('Open Instagram and add this page\'s link to your Story.'); });
        }
    }

    /* ---------------- tabs + search ---------------- */
    var tab = 'all', q = '';
    function filter() {
        var shown = 0;
        $$('[data-card]').forEach(function (c) {
            var ok = (tab === 'all' || c.dataset.type === tab) && (!q || c.dataset.search.indexOf(q) > -1);
            c.hidden = !ok; if (ok) shown++;
        });
        var empty = $('#rd-empty');
        if (empty && $$('[data-card]').length) empty.hidden = shown > 0;
    }

    /* ---------------- Campus Pulse poll ---------------- */
    function renderPoll(p) {
        var box = $('[data-poll-body]'); if (!box) return;
        if (p.status === 'none') { box.innerHTML = ''; return; }
        var closed = p.status === 'closed';
        var html = '<p class="rd-poll-q">' + esc(p.question) + '</p>';
        if (!p.voted && !closed) {
            html += p.options.map(function (o) { return '<button type="button" class="rd-poll-opt" data-vote="' + esc(o.key) + '">' + esc(o.label) + '</button>'; }).join('');
            html += '<p class="rd-poll-total">One tap to vote. No sign-in needed. Voting closes ' + esc(p.ends) + '.</p>';
        } else {
            html += p.options.map(function (o) {
                return '<div class="rd-result' + (o.key === p.voted ? ' mine' : '') + '"><i style="width:' + o.pct + '%"></i><span>' + esc(o.label) + '</span><span>' + o.pct + '%</span></div>';
            }).join('');
            html += '<p class="rd-poll-total">' + p.total + ' vote' + (p.total === 1 ? '' : 's') +
                (closed ? ' · Poll closed ' + esc(p.ends) : ' · Closes ' + esc(p.ends)) + '</p>';
        }
        box.innerHTML = html;
    }
    try { var pd = $('#rd-poll-data'); if (pd) renderPoll(JSON.parse(pd.textContent)); } catch (e) { }

    /* ---------------- events ---------------- */
    document.addEventListener('click', function (e) {
        var t = e.target;
        var tabBtn = t.closest('[data-tab]');
        if (tabBtn) { tab = tabBtn.dataset.tab; $$('[data-tab]').forEach(function (b) { b.classList.toggle('active', b === tabBtn); }); filter(); return; }

        var kindBtn = t.closest('[data-react] [data-kind]');
        if (kindBtn) { var rb = kindBtn.closest('[data-react]'); rb.classList.remove('open'); react(rb, kindBtn.dataset.kind); return; }
        var main = t.closest('.rd-react-main');
        if (main) {
            var rb2 = main.parentNode;
            if (pressed) { pressed = false; return; }              // long-press just opened the picker
            if (rb2.classList.contains('open')) { rb2.classList.remove('open'); return; }
            react(rb2, 'heart'); return;                           // tap: love it, or tap again to undo
        }

        var sb = t.closest('[data-share-btn]');
        if (sb) { var sh = sb.closest('[data-share]'); var o = !sh.classList.contains('open'); closeMenus(); sh.classList.toggle('open', o); sb.setAttribute('aria-expanded', o); return; }
        var sd = t.closest('[data-share-do]');
        if (sd) { share(sd.closest('[data-share]'), sd.dataset.shareDo); closeMenus(); return; }

        var sv = t.closest('[data-save]');
        if (sv) { toggleSave(sv.dataset.id, sv.dataset.title, sv.dataset.url); return; }
        var un = t.closest('[data-unsave]');
        if (un) { setSaved(getSaved().filter(function (s) { return String(s.id) !== un.dataset.unsave; })); renderSaved(); return; }

        var vote = t.closest('[data-vote]');
        if (vote) { post('/news/poll/vote', { option: vote.dataset.vote }).then(renderPoll).catch(function () { toast('Could not record your vote.'); }); return; }

        if (t.closest('[data-totop]')) {
            var calm = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
            window.scrollTo({ top: 0, behavior: calm ? 'auto' : 'smooth' }); return;
        }
        if (t.closest('#rd-saved-open') || t.closest('[data-open-saved]')) { e.preventDefault(); drawerOpen(true); return; }
        if (t.closest('#rd-saved-close') || t === scrim) { drawerOpen(false); return; }
        closeMenus();
        $$('.rd-react.open').forEach(function (r) { if (!r.contains(t)) r.classList.remove('open'); });
    });
    function closeMenus() { $$('.rd-share.open').forEach(function (s) { s.classList.remove('open'); }); }
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape') { drawerOpen(false); closeMenus(); } });
    var qi = $('#rd-q'), onFeed = !!$('#rd-feed');
    if (qi) {
        qi.addEventListener('input', function () { q = qi.value.trim().toLowerCase(); if (onFeed) filter(); });
        var pre = new URLSearchParams(location.search).get('q');   // from a search made on another page
        if (onFeed && pre) { qi.value = pre; q = pre.trim().toLowerCase(); filter(); }
        $('#rd-search-form').addEventListener('submit', function (e) { if (onFeed) e.preventDefault(); });
    }

    // footer "Sections" links arrive as /#News etc.: open that tab on the feed
    function tabFromHash() {
        var h = decodeURIComponent(location.hash.slice(1));
        var b = h && $('.rd-tab[data-tab="' + h + '"]');
        if (b) { b.click(); window.scrollTo(0, 0); }
    }
    window.addEventListener('hashchange', tabFromHash);
    tabFromHash();

    // landing: the works advance on a timer only. Scrolling the page never moves them, so
    // the reader can scroll straight past to the rest of the page. Every 5 seconds the cover
    // reel slides up to the next work and the text swaps. Section buttons and "Next story"
    // jump to a work and restart the 5 seconds. It loops back to the first work after the last.
    var stage = $('.lp-stage'), reel = $('.lp-reel');
    if (stage && reel) {
        var texts = $$('.lp-text'), timerBar = $('.lp-timer');
        var n = texts.length, idx = 0, timer = null, inView = false, SLIDE_MS = 900, AUTO_MS = 3000;
        var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

        function setReel(i, animate) {
            reel.style.transition = animate && !reduce ? 'transform ' + SLIDE_MS + 'ms cubic-bezier(.65,0,.35,1)' : 'none';
            reel.style.transform = 'translateY(' + (-i * 100) + '%)';
        }
        function show(i) {
            var prev = idx % n;
            idx = i;
            setReel(idx, true);
            var on = idx % n;
            // the text slides on the same clock as the cover: old one up and out, new one up from below.
            // An incoming text that is still parked above (few works, or the restart) is first dropped
            // below without animation, so it always rises instead of sliding back down.
            var inc = texts[on];
            if (inc !== texts[prev] && inc.classList.contains('is-prev')) { inc.classList.remove('is-prev'); void inc.offsetWidth; }
            texts.forEach(function (t, k) {
                t.classList.toggle('is-on', k === on);
                t.classList.toggle('is-prev', k === prev && prev !== on);
            });
            if (idx === n) {            // slid onto the extra copy of the first work: jump back to the real one unseen
                setTimeout(function () { if (idx === n) { idx = 0; setReel(0, false); } }, SLIDE_MS + 50);
            }
            schedule();
        }
        function clearBar() {
            clearTimeout(timer);
            if (timerBar) timerBar.classList.remove('run');
        }
        function schedule() {
            clearBar();
            if (reduce || document.hidden || !inView || n < 2) return;
            if (timerBar) {
                timerBar.firstElementChild.style.animationDuration = AUTO_MS + 'ms';
                void timerBar.offsetWidth; timerBar.classList.add('run');
            }
            timer = setTimeout(function () { show(idx % n + 1); }, AUTO_MS);
        }
        // only run while the section is actually on screen
        if ('IntersectionObserver' in window) {
            new IntersectionObserver(function (en) { inView = en[0].isIntersecting; schedule(); }, { threshold: .5 }).observe(stage);
        } else { inView = true; }
        document.addEventListener('visibilitychange', schedule);

        document.addEventListener('click', function (e) {
            var go = e.target.closest('[data-go]');
            if (go) { e.preventDefault(); show(+go.dataset.go); }
        });
        schedule();
    }

    renderSaved();
})();
