    const state = {
      sourceVersion: 0,
      busy: false,
      backend: "",
      sourceTab: "social",
      mediaMode: "none",
      media: {
        blob: null,
        objectUrl: "",
        title: "",
        author: "",
        platform: "",
        duration: 0,
        transcript: [],
        words: [],
        tracking: [],
        id: null,
        cleanDownloadUrl: "",
        socialUrl: "",
        width: 1280,
        height: 720,
      },
      social: {
        platform: "",
        url: "",
      },
      clips: [],
      filteredClips: [],
      selectedIdx: 0,
      visual: {
        frameMode: "split",
        fcSource: "top-center",
        fcDest: "top",
        fcZoom: 1.0,
        panX: 0,
        captionStyle: "opus",
        captionsOn: true,
        watermarkPos: "hidden",
      },
      playback: {
        rafId: null,
        playing: false,
        muted: false,
      },
      audioGraph: {
        ctx: null,
        srcNode: null,
        destNode: null,
        gain: null,
      },
      renderJob: {
        active: false,
        cancelled: false,
        recorder: null,
        finish: null,
        abort: null,
        lastBlob: null,
        lastUrl: "",
        lastFilename: "",
      },
      library: {
        items: [],
        blobUrls: {},
      }
    };

    function showToast(msg) {
      const box = document.getElementById("toast-container");
      if (!box) return;
      const item = document.createElement("div");
      item.className = "toast-item";
      item.textContent = msg;
      box.appendChild(item);
      setTimeout(() => item.remove(), 5500);
    }

    function scrollToLibrary() {
      const sec = document.getElementById("library-section");
      if (sec) sec.scrollIntoView({ behavior: "smooth", block: "start" });
      refreshLibrary();
    }

    function applyGamePreset(presetKey) {
      document.querySelectorAll(".preset-btn").forEach(b => {
        b.classList.toggle("active", b.dataset.preset === presetKey);
      });

      if (presetKey === "gta") {
        setFrameMode("split");
        document.getElementById("fc-source-select").value = "top-center";
        state.visual.fcSource = "top-center";
        document.getElementById("fc-dest-select").value = "top";
        state.visual.fcDest = "top";
        setCaptionPreset("opus", false);
      } else if (presetKey === "fps") {
        setFrameMode("split");
        document.getElementById("fc-source-select").value = "bottom-center";
        state.visual.fcSource = "bottom-center";
        document.getElementById("fc-dest-select").value = "bottom";
        state.visual.fcDest = "bottom";
        setCaptionPreset("rgb", false);
      } else if (presetKey === "moba") {
        setFrameMode("blur");
        setCaptionPreset("hormozi", false);
      } else if (presetKey === "react") {
        setFrameMode("pip");
        document.getElementById("fc-source-select").value = "top-center";
        state.visual.fcSource = "top-center";
        document.getElementById("fc-dest-select").value = "top";
        state.visual.fcDest = "top";
        setCaptionPreset("viral", false);
      } else {
        setFrameMode("autotrack");
        setCaptionPreset("opus", false);
      }
      showToast("Modelo aplicado!");
    }

    function switchSourceTab(tab) {
      state.sourceTab = tab;
      document.getElementById("tab-social").classList.toggle("active", tab === "social");
      document.getElementById("tab-local").classList.toggle("active", tab === "local");
      document.getElementById("panel-social").classList.toggle("hidden", tab !== "social");
      document.getElementById("panel-local").classList.toggle("hidden", tab !== "local");
    }

    function parseSocialLink(raw) {
      let s = String(raw || "").trim().replace(/&amp;/g, "&");
      if (!s) return null;
      const match = s.match(/https?:\/\/[^\s<>]+/i);
      if (match) s = match[0].replace(/[.,;)]+$/, "");
      if (!/^https?:\/\//i.test(s)) s = "https://" + s;
      try {
        const u = new URL(s);
        const host = u.hostname.toLowerCase().replace(/^www\./, "");
        if (!host || !host.includes(".")) return null;

        if (host.includes("youtube.com") || host === "youtu.be") {
          return { platform: "YouTube", url: u.href, color: "#f87171", bg: "rgba(248,113,113,0.16)" };
        }
        if (host.includes("instagram.com") || host.includes("instagr.am")) {
          return { platform: "Instagram", url: u.href, color: "#f472b6", bg: "rgba(244,114,182,0.16)" };
        }
        if (host.includes("facebook.com") || host === "fb.watch" || host === "fb.com" || host.endsWith(".facebook.com")) {
          return { platform: "Facebook", url: u.href, color: "#60a5fa", bg: "rgba(96,165,250,0.16)" };
        }
        if (host.includes("kwai.com") || host.includes("kwai-video.com") || host.includes("kwai.net")) {
          return { platform: "Kwai", url: u.href, color: "#fb923c", bg: "rgba(251,146,60,0.16)" };
        }
        if (host.includes("tiktok.com") || host.includes("tiktokv.com")) {
          return { platform: "TikTok", url: u.href, color: "#2dd4bf", bg: "rgba(45,212,191,0.16)" };
        }
        if (host === "x.com" || host.includes("twitter.com")) {
          return { platform: "X / Twitter", url: u.href, color: "#e4e4e7", bg: "rgba(228,228,231,0.16)" };
        }
        const label = host.split(".")[0].charAt(0).toUpperCase() + host.split(".")[0].slice(1);
        return { platform: label, url: u.href, color: "#34d399", bg: "rgba(52,211,153,0.16)" };
      } catch (_) {
        return null;
      }
    }

    async function pasteFromClipboard() {
      try {
        const txt = await navigator.clipboard.readText();
        if (txt) {
          const inp = document.getElementById("social-url-input");
          inp.value = txt.trim();
          onSocialUrlChanged(txt.trim());
        }
      } catch (_) {
        document.getElementById("social-url-input").focus();
        showToast("Toque no campo acima e selecione Colar.");
      }
    }

    function clearSocialInput() {
      document.getElementById("social-url-input").value = "";
      resolveSocialLink("");
    }

    function onSocialUrlChanged(val) {
      resolveSocialLink(val);
    }

    function resolveSocialLink(rawUrl) {
      const hasText = !!String(rawUrl || "").trim();
      document.getElementById("social-clear-btn").classList.toggle("hidden", !hasText);
      const card = document.getElementById("social-meta-card");
      card.classList.toggle("hidden", !hasText);

      const parsed = parseSocialLink(rawUrl);
      const badge = document.getElementById("social-platform-badge");
      const titleEl = document.getElementById("social-title-text");
      const authorEl = document.getElementById("social-author-text");
      const noteEl = document.getElementById("social-stream-note");

      if (parsed) {
        state.social.platform = parsed.platform;
        state.social.url = parsed.url;
        badge.style.background = parsed.bg;
        badge.style.color = parsed.color;
        badge.textContent = `${parsed.platform} reconhecido ✓`;
        authorEl.textContent = "Qualidade Máxima • Sem Marca d'Água";
        titleEl.textContent = parsed.url;
        noteEl.textContent = 'Toque em "Preparar cortes virais" para baixar limpo e editar.';
        return parsed;
      }

      state.social.platform = "";
      state.social.url = "";
      badge.style.background = "rgba(245,158,11,0.16)";
      badge.style.color = "#fbbf24";
      badge.textContent = "Confira o link";
      authorEl.textContent = "";
      titleEl.textContent = "Link inválido";
      noteEl.textContent = "Cole o endereço completo do vídeo (YouTube, Instagram, TikTok, Kwai, Facebook, X, etc.).";
      return null;
    }

    async function handleLocalVideoFile(e) {
      const file = e.target && e.target.files && e.target.files[0];
      if (!file || state.busy || state.renderJob.active) return;
      if (file.type && !file.type.startsWith("video/")) {
        showToast("Escolha um arquivo de vídeo.");
        return;
      }
      setAppBusy(true);
      try {
        await loadVideoBlobIntoStudio(file, file.name, "Arquivo Local");
      } catch (_) {
        document.getElementById("pipeline-card").classList.remove("hidden");
        try {
          await ensureBackend();
          const media = await runRawJob(
            "/api/upload?filename=" + encodeURIComponent(file.name),
            file,
            (p, m) => setPipeProgress(p, "Convertendo arquivo para o editor...", m)
          );
          await loadVideoBlobIntoStudio(null, media.title, "Arquivo Local", media);
          switchSourceTab("local");
          setPipeProgress(100, "Vídeo pronto", 'Toque em "Preparar cortes virais" para analisar.');
        } catch (conversionError) {
          showToast(conversionError.message);
        }
      } finally {
        setAppBusy(false);
        e.target.value = "";
      }
    }

    async function loadVideoBlobIntoStudio(blob, title, sourceLabel, serverMedia = null) {
      const version = ++state.sourceVersion;
      stopPreview();
      const vid = document.getElementById("master-video");
      vid.crossOrigin = "anonymous";
      const previousUrl = state.media.objectUrl;
      const url = blob ? URL.createObjectURL(blob) : mediaUrl(serverMedia.url);
      state.mediaMode = "loading";
      document.getElementById("active-media-title").textContent = title;
      document.getElementById("active-media-sub").textContent = "Carregando vídeo...";
      vid.muted = state.playback.muted;
      try {
        await new Promise((resolve, reject) => {
          let timer;
          const cleanup = () => {
            clearTimeout(timer);
            vid.removeEventListener("loadedmetadata", loaded);
            vid.removeEventListener("error", failed);
          };
          const failed = () => {
            cleanup();
            reject(new Error("Não foi possível abrir este formato no navegador. Convertendo no servidor..."));
          };
          const loaded = () => {
            if (!Number.isFinite(vid.duration) || vid.duration <= 0) {
              const finish = () => {
                vid.removeEventListener("durationchange", changed);
                cleanup();
                vid.currentTime = 0;
                resolve();
              };
              const changed = () => {
                if (Number.isFinite(vid.duration) && vid.duration > 0) finish();
              };
              vid.addEventListener("durationchange", changed);
              vid.addEventListener("seeked", () => { if (Number.isFinite(vid.duration)) finish(); }, { once: true });
              vid.currentTime = 1e9;
            } else {
              cleanup();
              resolve();
            }
          };
          vid.addEventListener("loadedmetadata", loaded);
          vid.addEventListener("error", failed);
          timer = setTimeout(() => { cleanup(); reject(new Error("Tempo esgotado ao carregar o vídeo.")); }, 30000);
          vid.src = url;
          vid.load();
        });
        if (version !== state.sourceVersion) return;
        state.media = {
          blob,
          objectUrl: blob ? url : "",
          title,
          author: sourceLabel,
          platform: serverMedia ? (serverMedia.platform || sourceLabel) : sourceLabel,
          duration: vid.duration,
          width: vid.videoWidth,
          height: vid.videoHeight,
          id: serverMedia ? serverMedia.id : null,
          url: serverMedia ? serverMedia.url : "",
          cleanDownloadUrl: serverMedia ? (serverMedia.cleanDownloadUrl || serverMedia.url) : "",
          transcript: serverMedia ? (serverMedia.transcript || []) : [],
          words: [],
          tracking: [],
          socialUrl: serverMedia ? (serverMedia.socialUrl || "") : "",
        };
        state.mediaMode = "canvas-video";
        state.clips = [];
        state.filteredClips = [];
        document.getElementById("studio-wrapper").classList.add("hidden");
        document.getElementById("active-media-sub").textContent = `${sourceLabel} • ${vid.videoWidth}×${vid.videoHeight} • Duração: ${fmtTime(vid.duration)}`;

        const rawDlBox = document.getElementById("clean-raw-download-box");
        const rawDlLink = document.getElementById("clean-raw-download-link");
        if (rawDlBox && rawDlLink && state.media.cleanDownloadUrl) {
          rawDlLink.href = mediaUrl(state.media.cleanDownloadUrl);
          rawDlBox.classList.remove("hidden");
        } else if (rawDlBox) {
          rawDlBox.classList.add("hidden");
        }

        if (blob) switchSourceTab("local");
        showToast("Vídeo carregado sem marca d'água e sem metadados!");
      } catch (error) {
        if (blob) URL.revokeObjectURL(url);
        if (version === state.sourceVersion) {
          state.mediaMode = "none";
          document.getElementById("active-media-sub").textContent = error.message;
        }
        throw error;
      } finally {
        if (previousUrl) URL.revokeObjectURL(previousUrl);
      }
    }

    async function generateTestVideoReal() {
      const btn = document.getElementById("btn-gen-test");
      if (btn.disabled || state.busy || state.renderJob.active) return;
      setAppBusy(true);
      btn.textContent = "⏳ Gerando...";

      try {
        const w = 1280, h = 720, dur = 12;
        const canvas = document.createElement("canvas");
        canvas.width = w;
        canvas.height = h;
        const ctx = canvas.getContext("2d");

        const AudioCtx = window.AudioContext || window.webkitAudioContext;
        const audioCtx = new AudioCtx();
        const dest = audioCtx.createMediaStreamDestination();
        const masterGain = audioCtx.createGain();
        masterGain.gain.value = 0.25;
        masterGain.connect(dest);

        const now = audioCtx.currentTime;
        for (let b = 0; b < dur * 2; b++) {
          const t = now + b * 0.5;
          const osc = audioCtx.createOscillator();
          const g = audioCtx.createGain();
          osc.type = (b >= 6 && b <= 10) || (b >= 16 && b <= 20) ? "sawtooth" : "triangle";
          osc.frequency.setValueAtTime(115, t);
          osc.frequency.exponentialRampToValueAtTime(45, t + 0.22);
          g.gain.setValueAtTime(0.55, t);
          g.gain.exponentialRampToValueAtTime(0.001, t + 0.26);
          osc.connect(g);
          g.connect(masterGain);
          osc.start(t);
          osc.stop(t + 0.28);
        }

        await audioCtx.resume();
        const stream = canvas.captureStream(60);
        dest.stream.getAudioTracks().forEach(t => stream.addTrack(t));

        const mime = ["video/mp4", "video/webm;codecs=vp9,opus", "video/webm"].find(m => MediaRecorder.isTypeSupported(m)) || "";
        const chunks = [];
        const rec = mime ? new MediaRecorder(stream, { mimeType: mime, videoBitsPerSecond: 4_000_000 }) : new MediaRecorder(stream);
        rec.ondataavailable = e => { if (e.data && e.data.size > 0) chunks.push(e.data); };

        const done = new Promise(res => {
          rec.onstop = () => {
            audioCtx.close();
            res(new Blob(chunks, { type: mime || "video/mp4" }));
          };
        });

        rec.start(200);
        const startT = performance.now();
        const loop = setInterval(() => {
          const el = (performance.now() - startT) / 1000;
          drawTestGameplay(ctx, w, h, el);
          if (el >= dur) {
            clearInterval(loop);
            rec.stop();
          }
        }, 1000 / 60);

        const blob = await done;
        await loadVideoBlobIntoStudio(blob, "BIGSIXX48_Gameplay_Teste." + (blob.type.includes("mp4") ? "mp4" : "webm"), "Vídeo Teste Real");
      } catch (_) {
        showToast("Erro ao gerar vídeo de teste.");
      } finally {
        setAppBusy(false);
        btn.textContent = "⚡ Gerar Vídeo Teste 60fps";
      }
    }

    function drawTestGameplay(ctx, w, h, t) {
      const peak = (t >= 2.5 && t <= 5) || (t >= 7.5 && t <= 10.5);
      ctx.fillStyle = peak ? "#1e0916" : "#09090b";
      ctx.fillRect(0, 0, w, h);

      const sx = w * 0.5 + Math.sin(t * 1.3) * (w * 0.25);
      const sy = h * 0.48 + Math.cos(t * 2.1) * 35;
      ctx.fillStyle = peak ? "#FF0033" : "#10b981";
      ctx.beginPath();
      ctx.arc(sx, sy, peak ? 56 : 40, 0, Math.PI * 2);
      ctx.fill();

      ctx.fillStyle = "#ffffff";
      ctx.font = "900 26px sans-serif";
      ctx.fillText(peak ? "🔥 JOGADA ÉPICA • CLUTCH!" : "⚡ GAMEPLAY AO VIVO", 36, 56);

      const drawCamBox = (x, y, cw, ch, label) => {
        ctx.fillStyle = "#18181d";
        ctx.fillRect(x, y, cw, ch);
        ctx.strokeStyle = peak ? "#FF0033" : "#34d399";
        ctx.lineWidth = 4;
        ctx.strokeRect(x, y, cw, ch);
        ctx.fillStyle = "#8b5cf6";
        ctx.beginPath();
        ctx.arc(x + cw / 2, y + ch / 2 - 6, 32, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = "#ffffff";
        ctx.font = "800 13px monospace";
        ctx.textAlign = "center";
        ctx.fillText(label, x + cw / 2, y + ch - 12);
        ctx.textAlign = "left";
      };

      drawCamBox((w - 240) / 2, 16, 240, 150, "FACECAM CENTRO TOPO");
      drawCamBox(w - 260, h - 180, 240, 160, "FACECAM @bigsixx48");
    }

    async function startViralAnalysis() {
      if (state.busy || state.renderJob.active) return;
      if (!document.getElementById("perm-check").checked) {
        showToast("Confirme a permissão de uso do conteúdo.");
        return;
      }
      const source = state.sourceTab;
      const parsed = source === "social" ? resolveSocialLink(document.getElementById("social-url-input").value) : null;
      if (source === "social" && !parsed) {
        showToast("Link inválido. Cole o endereço completo do vídeo.");
        return;
      }
      if (source === "local" && state.mediaMode !== "canvas-video") {
        showToast("Escolha um arquivo do celular ou gere o vídeo de teste.");
        return;
      }

      setAppBusy(true);
      document.getElementById("pipeline-card").classList.remove("hidden");
      document.getElementById("pipeline-card").scrollIntoView({ behavior: "smooth", block: "center" });

      try {
        await ensureBackend();
        if (source === "social" && (state.media.socialUrl !== parsed.url || !state.media.id)) {
          setPipeProgress(3, `Baixando vídeo do ${parsed.platform}...`, "Buscando melhor qualidade sem marca d'água...");
          const media = await runJob(
            "/api/import",
            { url: parsed.url },
            (p, m) => setPipeProgress(Math.round(p * 0.45), `Importando do ${parsed.platform}...`, m)
          );
          media.socialUrl = parsed.url;
          await loadVideoBlobIntoStudio(null, media.title, media.platform || parsed.platform, media);
          document.getElementById("social-title-text").textContent = media.title;
          document.getElementById("social-author-text").textContent = media.author || parsed.platform;
        }

        if (!state.media.id) {
          setPipeProgress(5, "Preparando arquivo...", "Limpando metadados e enviando para análise...");
          const media = await runRawJob(
            "/api/upload?filename=" + encodeURIComponent(state.media.title),
            state.media.blob,
            (p, m) => setPipeProgress(Math.round(p * 0.45), "Preparando arquivo...", m)
          );
          state.media.id = media.id;
          state.media.url = media.url;
          state.media.cleanDownloadUrl = media.cleanDownloadUrl || media.url;
        }

        const count = Number(document.getElementById("clip-count-select").value);
        const [minDuration, maxDuration] = document.getElementById("clip-duration-select").value.split("-").map(Number);
        const focus = document.getElementById("focus-keywords-input").value.trim();

        const result = await runJob(
          "/api/analyze",
          { mediaId: state.media.id, count, minDuration, maxDuration, focus },
          (p, m) => setPipeProgress(45 + Math.round(p * 0.54), "Analisando vídeo...", m)
        );

        if (!result.clips || !result.clips.length) {
          throw new Error("A análise não retornou cortes. Tente outro vídeo.");
        }

        state.media.transcript = result.transcript || [];
        state.media.words = result.words || [];
        state.media.tracking = result.tracking || [];
        state.clips = result.clips;
        state.filteredClips = [...state.clips];
        state.selectedIdx = 0;

        document.getElementById("find-moment-input").value = "";
        document.getElementById("studio-wrapper").classList.remove("hidden");
        document.getElementById("studio-source-badge").textContent = `${state.media.platform || "9:16"} • Zero Metadata`;

        setPipeProgress(
          100,
          "Cortes prontos!",
          result.hasSpeech
            ? "Vídeo limpo sem marca d'água! Edite e exporte sem metadados."
            : "Trechos selecionados pelos picos de áudio e ação!"
        );

        renderClipCards();
        selectClip(0);
        document.getElementById("studio-wrapper").scrollIntoView({ behavior: "smooth", block: "start" });
      } catch (error) {
        setPipeProgress(0, "Não foi possível preparar os cortes", error.message);
        showToast(error.message);
      } finally {
        setAppBusy(false);
      }
    }

    function setPipeProgress(pct, title, desc) {
      document.getElementById("pipe-bar").style.width = `${pct}%`;
      document.getElementById("pipe-pct-label").textContent = `${pct}%`;
      document.getElementById("pipe-step-title").textContent = title;
      document.getElementById("pipe-step-desc").textContent = desc;
    }

    function setAppBusy(busy) {
      state.busy = busy;
      document.getElementById("btn-run-ai").disabled = busy;
      document.getElementById("btn-gen-test").disabled = busy;
      document.getElementById("social-url-input").disabled = busy;
      document.getElementById("local-video-input").disabled = busy;
      document.getElementById("tab-local").disabled = busy;
      document.getElementById("tab-social").disabled = busy;
    }

    function filterRenderedClips(query) {
      const q = (query || "").trim().toLowerCase();
      if (!q) document.getElementById("find-moment-input").value = "";
      state.filteredClips = q
        ? state.clips.filter(c =>
            c.title.toLowerCase().includes(q) ||
            c.hookReason.toLowerCase().includes(q) ||
            (c.captions || []).some(cap => cap.text.toLowerCase().includes(q))
          )
        : [...state.clips];
      renderClipCards();
    }

    function renderClipCards() {
      const box = document.getElementById("clips-list-container");
      document.getElementById("clips-total-num").textContent = state.filteredClips.length;
      box.innerHTML = "";

      state.filteredClips.forEach((clip) => {
        const realIdx = state.clips.findIndex(x => x.id === clip.id);
        const isSel = realIdx === state.selectedIdx;
        const el = document.createElement("div");
        el.className = `clip-item ${isSel ? "selected" : ""}`;
        el.onclick = () => selectClip(realIdx);

        el.innerHTML = `
          <div style="display:flex;justify-content:space-between;align-items:center;gap:6px;">
            <span style="font-size:11px;font-weight:900;color:#ffffff;">#${clip.rank} • <span style="color:#34d399;">${clip.viralScore}/100</span></span>
            <span style="font-size:10px;font-weight:800;padding:2px 7px;border-radius:6px;background:rgba(139,92,246,0.2);color:#ddd6fe;">${escapeHtml(clip.category)}</span>
          </div>
          <div style="font-size:13px;font-weight:800;color:#ffffff;">${escapeHtml(clip.title)}</div>
          <div style="font-size:11px;color:#a1a1aa;">${escapeHtml(clip.hookReason)}</div>
          <div style="display:flex;justify-content:space-between;align-items:center;padding-top:6px;border-top:1px solid #27272a;font-size:11px;">
            <span style="font-family:monospace;color:#d4d4d8;">${fmtTime(clip.startTime)} — ${fmtTime(clip.endTime)} (${clip.duration}s)</span>
            <span style="color:#FF0033;font-weight:800;">${isSel ? "● Editando" : "Abrir →"}</span>
          </div>
        `;
        box.appendChild(el);
      });
    }

    function selectClip(idx) {
      const clip = state.clips[idx];
      if (!clip || state.renderJob.active) return;
      state.selectedIdx = idx;
      renderClipCards();

      document.getElementById("active-clip-tag").textContent = `Corte #${clip.rank}`;
      document.getElementById("time-range-lbl").textContent = `${fmtTime(clip.startTime)} — ${fmtTime(clip.endTime)}`;
      document.getElementById("time-end-lbl").textContent = `${clip.duration.toFixed(1)}s`;
      document.getElementById("trim-start-num").value = clip.startTime;
      document.getElementById("trim-end-num").value = clip.endTime;

      const scrubber = document.getElementById("clip-scrubber");
      scrubber.min = 0;
      scrubber.max = clip.duration;
      scrubber.value = 0;

      document.getElementById("out-title-input").value = clip.title;
      document.getElementById("out-desc-input").value = clip.description;
      document.getElementById("out-tags-input").value = clip.hashtags.join(" ");

      startCanvasPreviewPlayer(clip);
    }

    function startCanvasPreviewPlayer(clip) {
      stopPreview();
      const vid = document.getElementById("master-video");
      const canvas = document.getElementById("studio-canvas");
      const ctx = canvas.getContext("2d");
      vid.muted = state.playback.muted;
      vid.currentTime = clip.startTime;
      vid.play().then(() => { state.playback.playing = true; }).catch(() => { state.playback.playing = false; });

      const loop = () => {
        if (!state.renderJob.active && state.mediaMode === "canvas-video") {
          const active = state.clips[state.selectedIdx];
          if (active && vid.readyState >= 2) {
            if (vid.ended || vid.currentTime >= active.endTime || vid.currentTime < active.startTime - 0.15) {
              vid.currentTime = active.startTime;
              if (state.playback.playing) vid.play().catch(() => {});
            }
            const rel = Math.max(0, Math.min(active.duration, vid.currentTime - active.startTime));
            document.getElementById("time-now-lbl").textContent = rel.toFixed(1) + "s";
            document.getElementById("clip-scrubber").value = rel;
            drawVerticalComposite(ctx, canvas.width, canvas.height, vid, active, rel);
          }
        }
        state.playback.rafId = requestAnimationFrame(loop);
      };
      state.playback.rafId = requestAnimationFrame(loop);
    }

    function drawVerticalComposite(ctx, outW, outH, videoEl, clip, relTime) {
      ctx.save();
      ctx.fillStyle = "#09090b";
      ctx.fillRect(0, 0, outW, outH);

      const vw = videoEl.videoWidth || 1280;
      const vh = videoEl.videoHeight || 720;
      const mode = state.visual.frameMode;
      const trackingPan = mode === "autotrack" ? trackedPan(videoEl.currentTime, vw, vh, outW / outH) : state.visual.panX;

      if (videoEl.readyState >= 2) {
        if (mode === "blur") {
          ctx.save();
          ctx.filter = "blur(24px) brightness(0.45)";
          const sBg = Math.max(outW / vw, outH / vh) * 1.12;
          ctx.drawImage(videoEl, (outW - vw * sBg) / 2, (outH - vh * sBg) / 2, vw * sBg, vh * sBg);
          ctx.restore();

          const fgW = outW * 0.94;
          const fgH = fgW * (vh / vw);
          ctx.drawImage(videoEl, (outW - fgW) / 2, (outH - fgH) / 2, fgW, fgH);
        } else if (mode === "split") {
          const camH = Math.round(outH * 0.35);
          const gameH = outH - camH;
          const camOnTop = state.visual.fcDest === "top" || state.visual.fcDest === "pip-top";

          const camY = camOnTop ? 0 : gameH;
          const gameY = camOnTop ? camH : 0;

          drawCroppedRegion(ctx, videoEl, 0, 0, vw, vh, 0, gameY, outW, gameH, state.visual.panX);

          const fcBox = computeFacecamSourceRect(vw, vh, state.visual.fcSource, state.visual.fcZoom);
          drawCroppedRegion(ctx, videoEl, fcBox.sx, fcBox.sy, fcBox.sw, fcBox.sh, 0, camY, outW, camH, 0);

          ctx.fillStyle = "#FF0033";
          ctx.fillRect(0, camOnTop ? camH - 2 : gameH - 2, outW, 4);
        } else if (mode === "pip") {
          drawCroppedRegion(ctx, videoEl, 0, 0, vw, vh, 0, 0, outW, outH, state.visual.panX);

          const fcBox = computeFacecamSourceRect(vw, vh, state.visual.fcSource, state.visual.fcZoom);
          const pipW = Math.round(outW * 0.44);
          const pipH = Math.round(pipW * 0.72);
          const pipX = Math.round((outW - pipW) / 2);
          const isTop = state.visual.fcDest === "top" || state.visual.fcDest === "pip-top";
          const pipY = isTop ? Math.round(outH * 0.09) : Math.round(outH * 0.70);

          ctx.save();
          roundRect(ctx, pipX, pipY, pipW, pipH, 16 * (outW / 540));
          ctx.clip();
          drawCroppedRegion(ctx, videoEl, fcBox.sx, fcBox.sy, fcBox.sw, fcBox.sh, pipX, pipY, pipW, pipH, 0);
          ctx.restore();

          ctx.strokeStyle = "#FF0033";
          ctx.lineWidth = 3 * (outW / 540);
          roundRect(ctx, pipX, pipY, pipW, pipH, 16 * (outW / 540));
          ctx.stroke();
        } else {
          drawCroppedRegion(ctx, videoEl, 0, 0, vw, vh, 0, 0, outW, outH, trackingPan);
        }
      }

      if (state.visual.watermarkPos !== "hidden") {
        drawWatermark(ctx, outW, outH);
      }

      if (state.visual.captionsOn && clip.captions && clip.captions.length > 0) {
        const line = clip.captions.find(c => relTime >= c.start && relTime <= c.end);
        if (line) drawKaraokeText(ctx, outW, outH, line, relTime);
      }

      ctx.restore();
    }

    function computeFacecamSourceRect(vw, vh, sourcePos, zoom) {
      const z = Math.max(1, Number(zoom) || 1);
      const sw = (vw * 0.36) / z;
      const sh = (vh * 0.38) / z;

      let sx = (vw - sw) / 2;
      if (sourcePos.includes("right")) sx = vw - sw;
      else if (sourcePos.includes("left")) sx = 0;

      let sy = sourcePos.startsWith("top") ? 0 : (vh - sh);
      return { sx, sy, sw, sh };
    }

    function drawCroppedRegion(ctx, videoEl, srcX, srcY, srcW, srcH, destX, destY, destW, destH, panPct) {
      const destRatio = destW / destH;
      const srcRatio = srcW / srcH;

      let rx = srcX, ry = srcY, rw = srcW, rh = srcH;
      if (srcRatio > destRatio) {
        rh = srcH;
        rw = srcH * destRatio;
        const maxShift = Math.max(0, srcW - rw);
        rx = srcX + maxShift * ((panPct + 100) / 200);
      } else {
        rw = srcW;
        rh = srcW / destRatio;
        ry = srcY + Math.max(0, (srcH - rh) / 2);
      }

      ctx.drawImage(videoEl, rx, ry, rw, rh, destX, destY, destW, destH);
    }

    function drawWatermark(ctx, w, h) {
      const sc = w / 540;
      const isBot = state.visual.watermarkPos === "bottom";
      const y = isBot ? h * 0.90 : h * 0.042;
      const txt = "@bigsixx48";

      ctx.save();
      ctx.font = `900 ${Math.round(14 * sc)}px sans-serif`;
      const tw = ctx.measureText(txt).width;
      const pw = tw + 30 * sc;
      const ph = 26 * sc;
      const px = (w - pw) / 2;

      ctx.fillStyle = "rgba(9, 9, 11, 0.72)";
      roundRect(ctx, px, y, pw, ph, ph / 2);
      ctx.fill();

      ctx.fillStyle = "#FF0033";
      ctx.beginPath();
      ctx.arc(px + 12 * sc, y + ph / 2, 3.5 * sc, 0, Math.PI * 2);
      ctx.fill();

      ctx.fillStyle = "#ffffff";
      ctx.textBaseline = "middle";
      ctx.fillText(txt, px + 21 * sc, y + ph / 2);
      ctx.restore();
    }

    function drawKaraokeText(ctx, w, h, line, relTime) {
      const sc = w / 540;
      const st = state.visual.captionStyle;
      let fontSize = Math.round(25 * sc);
      ctx.save();
      ctx.font = `900 ${fontSize}px sans-serif`;
      ctx.textBaseline = "middle";

      const words = line.text.split(/\s+/).filter(Boolean);
      const span = Math.max(0.25, line.end - line.start);
      const activeWord = Math.floor(Math.max(0, Math.min(0.99, (relTime - line.start) / span)) * words.length);

      const naturalWidth = ctx.measureText(words.join(" ")).width;
      if (naturalWidth > w * 0.88) {
        fontSize = Math.max(8 * sc, fontSize * (w * 0.88) / naturalWidth);
        ctx.font = `900 ${fontSize}px sans-serif`;
      }
      const spaceW = ctx.measureText(" ").width;
      const totalW = ctx.measureText(words.join(" ")).width;
      let x = (w - totalW) / 2;
      const y = h * 0.62;

      words.forEach((word, idx) => {
        const ww = ctx.measureText(word).width;
        const active = idx === activeWord;

        if (active) {
          ctx.fillStyle = st === "rgb" ? "#8b5cf6" : st === "viral" ? "#FF0033" : "#10b981";
          roundRect(ctx, x - 5 * sc, y - fontSize * 0.6, ww + 10 * sc, fontSize * 1.2, 6 * sc);
          ctx.fill();
        }

        ctx.strokeStyle = "#000000";
        ctx.lineWidth = 5 * sc;
        ctx.strokeText(word, x, y);

        ctx.fillStyle = active && st === "opus" ? "#09090b" : st === "hormozi" && active ? "#fde047" : "#ffffff";
        ctx.fillText(word, x, y);
        x += ww + spaceW;
      });
      ctx.restore();
    }

    function roundRect(ctx, x, y, w, h, r) {
      ctx.beginPath();
      ctx.moveTo(x + r, y);
      ctx.arcTo(x + w, y, x + w, y + h, r);
      ctx.arcTo(x + w, y + h, x, y + h, r);
      ctx.arcTo(x, y + h, x, y, r);
      ctx.arcTo(x, y, x + w, y, r);
      ctx.closePath();
    }

    function setFrameMode(mode) {
      state.visual.frameMode = mode;
      document.querySelectorAll(".option-btn").forEach(b => {
        b.classList.toggle("active", b.dataset.mode === mode);
      });
      const showCam = mode === "split" || mode === "pip";
      document.getElementById("facecam-controls-box").classList.toggle("hidden", !showCam);
    }

    function updateFacecamZoom(val) {
      state.visual.fcZoom = Number(val) || 1;
      document.getElementById("fc-zoom-lbl").textContent = `${state.visual.fcZoom.toFixed(2)}x`;
    }

    function updatePanX(val) {
      state.visual.panX = Number(val) || 0;
      document.getElementById("pan-x-lbl").textContent = `${state.visual.panX}%`;
    }

    function setCaptionsEnabled(enabled) {
      state.visual.captionsOn = !!enabled;
      const btnOn = document.getElementById("btn-captions-on");
      const btnOff = document.getElementById("btn-captions-off");
      const statusLbl = document.getElementById("captions-status-lbl");
      const stylesWrap = document.getElementById("caption-styles-wrap");

      if (btnOn) btnOn.className = enabled ? "chip-btn active-green" : "chip-btn";
      if (btnOff) btnOff.className = !enabled ? "chip-btn active-red" : "chip-btn";
      if (statusLbl) {
        statusLbl.textContent = enabled ? "Ativadas" : "Desativadas (vídeo limpo)";
        statusLbl.style.color = enabled ? "#34d399" : "#fda4af";
      }
      if (stylesWrap) {
        stylesWrap.style.opacity = enabled ? "1" : "0.45";
      }
    }

    function setCaptionPreset(style, autoEnable = true) {
      state.visual.captionStyle = style;
      document.querySelectorAll(".style-chip").forEach(b => {
        b.classList.toggle("active", b.dataset.style === style);
      });
      if (autoEnable && !state.visual.captionsOn) {
        setCaptionsEnabled(true);
      }
    }

    function setWatermarkPosition(pos) {
      state.visual.watermarkPos = pos;
      document.querySelectorAll(".wm-chip").forEach(b => {
        b.classList.toggle("active", b.dataset.wm === pos);
      });
    }

    function togglePlayPause() {
      if (state.renderJob.active || state.mediaMode !== "canvas-video") return;
      const vid = document.getElementById("master-video");
      if (vid.paused) {
        vid.play().then(() => { state.playback.playing = true; }).catch(() => showToast("Toque novamente para reproduzir."));
      } else {
        vid.pause();
        state.playback.playing = false;
      }
    }

    function restartClip() {
      if (state.renderJob.active) return;
      const clip = state.clips[state.selectedIdx];
      if (!clip) return;
      const vid = document.getElementById("master-video");
      vid.currentTime = clip.startTime;
      vid.play().then(() => { state.playback.playing = true; }).catch(() => { state.playback.playing = false; });
    }

    function toggleMute() {
      state.playback.muted = !state.playback.muted;
      document.getElementById("master-video").muted = state.playback.muted;
      document.getElementById("btn-mute-toggle").textContent = state.playback.muted ? "🔇 Mudo" : "🔊 Som";
    }

    function seekActiveClip(sec) {
      const clip = state.clips[state.selectedIdx];
      if (!clip || state.renderJob.active || state.mediaMode !== "canvas-video") return;
      document.getElementById("master-video").currentTime = Math.max(
        clip.startTime,
        Math.min(clip.endTime, clip.startTime + Number(sec))
      );
    }

    function applyManualTrim() {
      const clip = state.clips[state.selectedIdx];
      if (!clip || state.renderJob.active) return;
      const total = state.media.duration;
      if (!Number.isFinite(total) || total <= 0) return;
      const minLength = Math.min(0.5, total);
      const start = Math.min(total - minLength, Math.max(0, Number(document.getElementById("trim-start-num").value) || 0));
      const end = Math.min(total, Math.max(start + minLength, Number(document.getElementById("trim-end-num").value) || total));
      const oldStart = clip.startTime;
      clip.startTime = start;
      clip.endTime = end;
      clip.duration = end - start;
      if (state.media.transcript.length) {
        clip.captions = captionsForRange(start, end);
      } else {
        clip.captions = (clip.captions || [])
          .map(c => ({
            ...c,
            start: Math.max(0, c.start + oldStart - start),
            end: Math.min(clip.duration, c.end + oldStart - start),
          }))
          .filter(c => c.end > c.start);
      }
      selectClip(state.selectedIdx);
    }

    async function exportEditedMp4() {
      if (state.renderJob.active || state.busy) return;
      const clip = state.clips[state.selectedIdx];
      if (!clip || state.mediaMode !== "canvas-video") {
        showToast("Importe o vídeo original antes de exportar.");
        return;
      }

      const vid = document.getElementById("master-video");
      const visual = JSON.parse(JSON.stringify(state.visual));
      state.renderJob.active = true;
      state.renderJob.cancelled = false;
      state.renderJob.abort = new AbortController();

      const btn = document.getElementById("btn-export-mp4");
      const box = document.getElementById("render-progress-box");
      const bar = document.getElementById("render-bar-fill");
      const pct = document.getElementById("render-pct-lbl");
      const status = document.getElementById("render-status-lbl");

      btn.disabled = true;
      box.classList.remove("hidden");
      bar.style.width = "0%";
      pct.textContent = "0%";
      status.textContent = "Preparando exportação em 1080×1920 sem metadados...";

      let stream, recorder, drawTimer;
      const tracks = [];

      try {
        if (!state.audioGraph.ctx) {
          try {
            const AudioCtx = window.AudioContext || window.webkitAudioContext;
            if (AudioCtx) {
              const ac = new AudioCtx();
              const srcNode = ac.createMediaElementSource(vid);
              const destNode = ac.createMediaStreamDestination();
              const gain = ac.createGain();
              gain.gain.value = 1;
              srcNode.connect(gain);
              gain.connect(destNode);
              gain.connect(ac.destination);
              state.audioGraph = { ctx: ac, srcNode, destNode, gain };
            }
          } catch (_) {}
        }
        if (state.audioGraph.ctx && state.audioGraph.ctx.state === "suspended") {
          state.audioGraph.ctx.resume().catch(() => {});
        }
        vid.muted = false;
        const unlockPlay = vid.play();
        if (unlockPlay && unlockPlay.catch) {
          unlockPlay.catch(() => {
            vid.muted = true;
            vid.play().catch(() => {});
          });
        }

        await ensureBackend();
        if (!window.MediaRecorder || !HTMLCanvasElement.prototype.captureStream) {
          throw new Error("Este navegador não suporta gravação de vídeo. Abra no Safari atualizado.");
        }

        const canvas = document.createElement("canvas");
        canvas.width = 1080;
        canvas.height = 1920;
        const ctx = canvas.getContext("2d");

        vid.pause();
        state.playback.playing = false;
        await seekVideo(vid, clip.startTime);
        if (state.renderJob.cancelled) return;

        drawVerticalComposite(ctx, 1080, 1920, vid, clip, 0);
        stream = canvas.captureStream(30);
        tracks.push(...stream.getVideoTracks());

        if (state.audioGraph.ctx) {
          await state.audioGraph.ctx.resume().catch(() => {});
          if (state.audioGraph.destNode) {
            for (const track of state.audioGraph.destNode.stream.getAudioTracks()) {
              stream.addTrack(track);
            }
          }
        }

        const mime = [
          "video/mp4;codecs=avc1,mp4a.40.2",
          "video/mp4",
          "video/webm;codecs=vp8,opus",
          "video/webm"
        ].find(m => MediaRecorder.isTypeSupported(m));

        const createSafeRecorder = (s) => {
          const attempts = [];
          if (mime) attempts.push(() => new MediaRecorder(s, { mimeType: mime, videoBitsPerSecond: 7500000, audioBitsPerSecond: 192000 }));
          if (mime) attempts.push(() => new MediaRecorder(s, { mimeType: mime }));
          attempts.push(() => new MediaRecorder(s));
          for (const fn of attempts) {
            try { return fn(); } catch (_) {}
          }
          return null;
        };

        recorder = createSafeRecorder(stream);
        if (!recorder) {
          const videoOnly = new MediaStream(stream.getVideoTracks());
          recorder = createSafeRecorder(videoOnly);
        }
        if (!recorder) {
          throw new Error("Não foi possível iniciar o gravador de vídeo neste navegador.");
        }

        state.renderJob.recorder = recorder;
        const chunks = [];
        recorder.addEventListener("dataavailable", e => {
          if (e.data && e.data.size) chunks.push(e.data);
        });

        const recorded = new Promise((resolve, reject) => {
          recorder.addEventListener("stop", () => resolve(new Blob(chunks, { type: recorder.mimeType || mime || "video/mp4" })), { once: true });
          recorder.addEventListener("error", () => reject(new Error("Falha no gravador de vídeo.")), { once: true });
        });

        recorder.start(250);
        try {
          vid.muted = false;
          await vid.play();
        } catch (_) {
          vid.muted = true;
          await vid.play();
        }

        status.textContent = "Gravando corte 1080×1920...";
        let lastTime = vid.currentTime;
        let lastMovement = performance.now();

        await new Promise((resolve, reject) => {
          state.renderJob.finish = resolve;
          drawTimer = setInterval(() => {
            if (state.renderJob.cancelled) { resolve(); return; }
            const rel = Math.max(0, vid.currentTime - clip.startTime);
            if (vid.currentTime !== lastTime) {
              lastTime = vid.currentTime;
              lastMovement = performance.now();
            }
            if (performance.now() - lastMovement > 20000) {
              reject(new Error("A reprodução parou durante a exportação. Tente novamente."));
              return;
            }
            const p = Math.min(90, Math.round((rel / clip.duration) * 90));
            bar.style.width = p + "%";
            pct.textContent = p + "%";
            const liveVisual = state.visual;
            state.visual = visual;
            drawVerticalComposite(ctx, 1080, 1920, vid, clip, rel);
            state.visual = liveVisual;
            if (vid.currentTime >= clip.endTime || vid.ended) resolve();
          }, 1000 / 30);
        });

        clearInterval(drawTimer);
        vid.pause();
        if (recorder.state !== "inactive") recorder.stop();
        const raw = await recorded;
        if (state.renderJob.cancelled) return;
        if (!raw.size) throw new Error("A gravação retornou um arquivo vazio.");

        const filename = `bigsixx48_corte_${String(clip.rank).padStart(2, "0")}_limpo.mp4`;
        const qs = new URLSearchParams({
          filename,
          title: clip.title || filename,
          platform: state.media.platform || "BIGSIXX48",
          duration: String(clip.duration || 0),
        });

        status.textContent = "Removendo metadados e salvando MP4...";
        const result = await runRawJob(
          "/api/finalize?" + qs.toString(),
          raw,
          (p, m) => {
            const n = 90 + Math.round(p * 0.1);
            bar.style.width = n + "%";
            pct.textContent = n + "%";
            if (m) status.textContent = m;
          },
          () => state.renderJob.cancelled
        );
        if (state.renderJob.cancelled) return;

        const response = await fetch(mediaUrl(result.url), { signal: state.renderJob.abort.signal });
        if (!response.ok) throw new Error("Não foi possível abrir o MP4 finalizado.");
        const blob = await response.blob();
        const finalBlob = new Blob([blob], { type: "video/mp4" });

        const serverItem = result.libraryItem || {};
        await saveItemToLocalLibrary({
          id: serverItem.id || ("loc_" + Date.now()),
          serverId: serverItem.id || "",
          filename,
          title: clip.title || filename,
          platform: state.media.platform || "BIGSIXX48",
          duration: clip.duration || 0,
          sizeBytes: finalBlob.size,
          createdAt: serverItem.createdAt || new Date().toISOString(),
          url: result.url || "",
          downloadUrl: result.downloadUrl || "",
          blob: finalBlob,
        });
        await refreshLibrary();

        if (!state.renderJob.cancelled) {
          openMp4ReadyModal(finalBlob, filename);
        }
      } catch (error) {
        if (!state.renderJob.cancelled) showToast(error.message);
      } finally {
        clearInterval(drawTimer);
        if (recorder && recorder.state !== "inactive") recorder.stop();
        for (const track of tracks) track.stop();
        state.renderJob.finish = null;
        state.renderJob.recorder = null;
        state.renderJob.abort = null;
        state.renderJob.active = false;
        vid.muted = state.playback.muted;
        btn.disabled = false;
        box.classList.add("hidden");
        if (state.clips.length) selectClip(state.selectedIdx);
      }
    }

    function cancelMp4Render() {
      state.renderJob.cancelled = true;
      if (state.renderJob.finish) state.renderJob.finish();
      if (state.renderJob.abort) state.renderJob.abort.abort();
    }

    function openMp4ReadyModal(mp4Blob, filename) {
      if (state.renderJob.lastUrl) URL.revokeObjectURL(state.renderJob.lastUrl);
      const url = URL.createObjectURL(mp4Blob);
      state.renderJob.lastBlob = mp4Blob;
      state.renderJob.lastUrl = url;
      state.renderJob.lastFilename = filename;

      document.getElementById("modal-mp4-filename").textContent = `${filename} (${(mp4Blob.size / (1024 * 1024)).toFixed(1)} MB) • 0 Metadados`;
      document.getElementById("modal-mp4-video").src = url;
      const dlLink = document.getElementById("modal-mp4-download-link");
      dlLink.href = url;
      dlLink.download = filename;

      document.getElementById("mp4-ready-modal").classList.remove("hidden");
      showToast("Corte limpo (sem metadados) pronto para baixar!");
    }

    function closeMp4Modal() {
      document.getElementById("modal-mp4-video").pause();
      document.getElementById("mp4-ready-modal").classList.add("hidden");
    }

    async function shareOrSaveMp4ToGallery() {
      const blob = state.renderJob.lastBlob;
      const filename = state.renderJob.lastFilename || "bigsixx48_corte_limpo.mp4";
      if (!blob) return;
      try {
        const file = new File([blob], filename, { type: "video/mp4" });
        if (navigator.canShare && navigator.canShare({ files: [file] })) {
          await navigator.share({ files: [file], title: filename });
          return;
        }
      } catch (_) {}
      document.getElementById("modal-mp4-download-link").click();
    }

    function openLibraryDb() {
      return new Promise((resolve, reject) => {
        if (!window.indexedDB) {
          reject(new Error("IndexedDB indisponível"));
          return;
        }
        const req = indexedDB.open("bigsixx48_library_db", 1);
        req.onupgradeneeded = () => {
          const db = req.result;
          if (!db.objectStoreNames.contains("clips")) {
            db.createObjectStore("clips", { keyPath: "id" });
          }
        };
        req.onsuccess = () => resolve(req.result);
        req.onerror = () => reject(req.error);
      });
    }

    async function saveItemToLocalLibrary(item) {
      try {
        const db = await openLibraryDb();
        await new Promise((resolve, reject) => {
          const tx = db.transaction("clips", "readwrite");
          tx.objectStore("clips").put(item);
          tx.oncomplete = () => resolve();
          tx.onerror = () => reject(tx.error);
        });
      } catch (_) {}
    }

    async function getAllLocalLibraryItems() {
      try {
        const db = await openLibraryDb();
        return await new Promise((resolve, reject) => {
          const tx = db.transaction("clips", "readonly");
          const req = tx.objectStore("clips").getAll();
          req.onsuccess = () => resolve(req.result || []);
          req.onerror = () => reject(req.error);
        });
      } catch (_) {
        return [];
      }
    }

    async function deleteLocalLibraryItem(id) {
      try {
        const db = await openLibraryDb();
        await new Promise((resolve, reject) => {
          const tx = db.transaction("clips", "readwrite");
          tx.objectStore("clips").delete(id);
          tx.oncomplete = () => resolve();
          tx.onerror = () => reject(tx.error);
        });
      } catch (_) {}
    }

    async function refreshLibrary() {
      const localItems = await getAllLocalLibraryItems();
      const mergedMap = new Map();

      for (const item of localItems) {
        mergedMap.set(item.id, item);
      }

      try {
        await ensureBackend();
        const data = await requestJson("/api/library");
        for (const srv of (data.items || [])) {
          if (!mergedMap.has(srv.id)) {
            mergedMap.set(srv.id, {
              ...srv,
              serverId: srv.id,
              blob: null,
            });
          } else {
            const existing = mergedMap.get(srv.id);
            existing.url = srv.url || existing.url;
            existing.downloadUrl = srv.downloadUrl || existing.downloadUrl;
          }
        }
      } catch (_) {}

      const list = Array.from(mergedMap.values()).sort(
        (a, b) => new Date(b.createdAt || 0).getTime() - new Date(a.createdAt || 0).getTime()
      );
      state.library.items = list;
      renderLibraryCards();
    }

    function renderLibraryCards() {
      const items = state.library.items || [];
      const countEl = document.getElementById("library-total-num");
      const headerCountEl = document.getElementById("header-lib-count");
      const emptyEl = document.getElementById("library-empty-state");
      const container = document.getElementById("library-list-container");

      if (countEl) countEl.textContent = items.length;
      if (headerCountEl) headerCountEl.textContent = items.length;
      if (!container) return;

      Object.values(state.library.blobUrls).forEach(u => URL.revokeObjectURL(u));
      state.library.blobUrls = {};
      container.innerHTML = "";

      if (!items.length) {
        if (emptyEl) emptyEl.classList.remove("hidden");
        return;
      }
      if (emptyEl) emptyEl.classList.add("hidden");

      items.forEach(item => {
        let videoSrc = "";
        if (item.blob instanceof Blob) {
          videoSrc = URL.createObjectURL(item.blob);
          state.library.blobUrls[item.id] = videoSrc;
        } else if (item.url) {
          videoSrc = mediaUrl(item.url);
        }

        const sizeMb = item.sizeBytes ? `${(item.sizeBytes / (1024 * 1024)).toFixed(1)} MB` : "MP4";
        const durTxt = item.duration ? `${Number(item.duration).toFixed(1)}s` : "9:16";
        const dateTxt = item.createdAt
          ? new Date(item.createdAt).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })
          : "";

        const card = document.createElement("div");
        card.className = "lib-card";
        card.innerHTML = `
          <div class="lib-video-wrap">
            ${videoSrc ? `<video src="${escapeHtml(videoSrc)}" controls playsinline preload="metadata"></video>` : ""}
          </div>
          <div style="display:flex;justify-content:space-between;align-items:center;gap:6px;">
            <span style="font-size:10px;font-weight:900;padding:2px 8px;border-radius:999px;background:rgba(16,185,129,0.18);color:#34d399;">
              ${escapeHtml(item.platform || "1080×1920")} • ${sizeMb} • ${durTxt}
            </span>
            <span style="font-size:11px;color:#a1a1aa;">${escapeHtml(dateTxt)}</span>
          </div>
          <div style="font-size:13px;font-weight:800;color:#fff;word-break:break-word;">${escapeHtml(item.title || item.filename)}</div>
          <div style="font-size:11px;color:#a1a1aa;font-family:monospace;word-break:break-all;">${escapeHtml(item.filename)}</div>
          <div style="display:flex;flex-direction:column;gap:6px;margin-top:4px;">
            <button type="button" class="btn btn-green" style="width:100%;" onclick="downloadLibraryItem('${escapeHtml(item.id)}')">
              ⬇️ Baixar no Celular (MP4)
            </button>
            <div style="display:grid;grid-template-columns:1fr auto;gap:6px;">
              <button type="button" class="btn btn-purple" onclick="shareLibraryItemToGallery('${escapeHtml(item.id)}')">
                📲 Salvar na Galeria
              </button>
              <button type="button" class="btn" style="color:#fda4af;" onclick="deleteLibraryItem('${escapeHtml(item.id)}')">
                🗑️
              </button>
            </div>
          </div>
        `;
        container.appendChild(card);
      });
    }

    function downloadLibraryItem(id) {
      const item = state.library.items.find(x => x.id === id);
      if (!item) return;

      if (item.blob instanceof Blob) {
        const url = state.library.blobUrls[item.id] || URL.createObjectURL(item.blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = item.filename || "bigsixx48_corte_limpo.mp4";
        document.body.appendChild(a);
        a.click();
        a.remove();
        showToast("Download iniciado!");
        return;
      }

      if (item.downloadUrl) {
        const a = document.createElement("a");
        a.href = mediaUrl(item.downloadUrl);
        a.download = item.filename || "bigsixx48_corte_limpo.mp4";
        document.body.appendChild(a);
        a.click();
        a.remove();
        showToast("Baixando MP4 do servidor...");
      }
    }

    async function shareLibraryItemToGallery(id) {
      const item = state.library.items.find(x => x.id === id);
      if (!item) return;
      try {
        let blob = item.blob;
        if (!(blob instanceof Blob) && item.url) {
          const resp = await fetch(mediaUrl(item.url));
          blob = await resp.blob();
        }
        if (blob instanceof Blob) {
          const file = new File([blob], item.filename || "bigsixx48_corte_limpo.mp4", { type: "video/mp4" });
          if (navigator.canShare && navigator.canShare({ files: [file] })) {
            await navigator.share({ files: [file], title: item.filename });
            return;
          }
        }
      } catch (_) {}
      downloadLibraryItem(id);
    }

    async function deleteLibraryItem(id) {
      await deleteLocalLibraryItem(id);
      try {
        await ensureBackend();
        await fetch(mediaUrl(`/api/library/${encodeURIComponent(id)}`), { method: "DELETE" });
      } catch (_) {}
      await refreshLibrary();
      showToast("Corte removido da biblioteca.");
    }

    function updateClipMeta(field, val) {
      const clip = state.clips[state.selectedIdx];
      if (!clip) return;
      clip[field] = val;
      if (field === "title") renderClipCards();
    }

    function updateClipTags(raw) {
      const clip = state.clips[state.selectedIdx];
      if (!clip) return;
      clip.hashtags = raw.split(/\s+/).filter(Boolean).map(t => t.startsWith("#") ? t : "#" + t);
    }

    function copyFullPostKit() {
      const clip = state.clips[state.selectedIdx];
      if (!clip) return;
      const txt = `${clip.title}\n\n${clip.description}\n\n${clip.hashtags.join(" ")}\n\nEdição: @bigsixx48`;
      const ta = document.createElement("textarea");
      ta.value = txt;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      ta.remove();
      showToast("Título, descrição e hashtags copiados!");
    }

    function downloadSrtFile() {
      const clip = state.clips[state.selectedIdx];
      if (!clip || !clip.captions || !clip.captions.length) {
        showToast("Sem legendas neste corte.");
        return;
      }
      const srt = clip.captions
        .map((c, i) => `${i + 1}\n${toSrtStamp(c.start)} --> ${toSrtStamp(c.end)}\n${c.text}\n`)
        .join("\n");
      triggerTextDownload(srt, `bigsixx48_corte_${String(clip.rank).padStart(2, "0")}.srt`);
    }

    function downloadTxtKit() {
      const clip = state.clips[state.selectedIdx];
      if (!clip) return;
      const txt = [
        `BIGSIXX48 — AI CLIPPER | @bigsixx48`,
        `Corte #${clip.rank} | Score: ${clip.viralScore}/100`,
        `Intervalo: ${fmtTime(clip.startTime)} - ${fmtTime(clip.endTime)} (${clip.duration}s)`,
        ``,
        `Título: ${clip.title}`,
        `Descrição: ${clip.description}`,
        `Hashtags: ${clip.hashtags.join(" ")}`
      ].join("\n");
      triggerTextDownload(txt, `bigsixx48_roteiro_corte_${String(clip.rank).padStart(2, "0")}.txt`);
    }

    function triggerTextDownload(content, filename) {
      const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
      const u = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = u;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(u), 4000);
    }

    function fmtTime(sec) {
      const s = Math.max(0, Math.floor(Number(sec) || 0));
      return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
    }

    function toSrtStamp(sec) {
      const ms = Math.max(0, Math.round((Number(sec) || 0) * 1000));
      const h = Math.floor(ms / 3600000);
      const m = Math.floor((ms % 3600000) / 60000);
      const s = Math.floor((ms % 60000) / 1000);
      return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")},${String(ms % 1000).padStart(3, "0")}`;
    }

    function escapeHtml(value) {
      return String(value).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
    }

    function stopPreview() {
      const vid = document.getElementById("master-video");
      if (vid) vid.pause();
      if (state.playback.rafId) cancelAnimationFrame(state.playback.rafId);
      state.playback.rafId = null;
      state.playback.playing = false;
    }

    function mediaUrl(path) {
      return new URL(path, state.backend || location.href).href;
    }

    async function ensureBackend() {
      let base = state.backend;
      if (!base && /^https?:$/.test(location.protocol)) base = location.origin;
      if (!base) {
        try { base = localStorage.getItem("bigsixx48-service") || ""; } catch (_) {}
        if (!base) {
          base = window.prompt("Cole o endereço HTTPS do serviço BIGSIXX48 online:", "") || "";
        }
      }
      if (!base) throw new Error("Abra o app pelo endereço online no Render.");
      let url;
      try { url = new URL(base); } catch (_) { throw new Error("Endereço do serviço inválido."); }
      if (!["http:", "https:"].includes(url.protocol)) throw new Error("Use um endereço HTTP ou HTTPS válido.");
      state.backend = url.origin;
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), 8000);
      try {
        const response = await fetch(mediaUrl("/api/health"), { signal: ctrl.signal });
        if (!response.ok) throw new Error();
        const health = await response.json();
        if (!health || !health.ok) throw new Error();
        try { localStorage.setItem("bigsixx48-service", state.backend); } catch (_) {}
        return health;
      } catch (_) {
        throw new Error("O serviço do app está acordando ou indisponível. Aguarde alguns segundos e tente novamente.");
      } finally {
        clearTimeout(timer);
      }
    }

    async function requestJson(path, options = {}) {
      const response = await fetch(mediaUrl(path), options);
      let data;
      try { data = await response.json(); } catch (_) { throw new Error("O serviço retornou uma resposta inválida."); }
      if (!response.ok) {
        throw new Error(typeof data.detail === "string" ? data.detail : (data.error || "Não foi possível concluir a operação."));
      }
      return data;
    }

    async function waitJob(job, progress, cancelled = () => false) {
      if (!job.jobId) throw new Error("O serviço não criou a tarefa.");
      const started = Date.now();
      while (true) {
        if (cancelled()) {
          await requestJson("/api/jobs/" + encodeURIComponent(job.jobId) + "/cancel", { method: "POST" }).catch(() => {});
          throw new Error("Operação cancelada.");
        }
        const result = await requestJson("/api/jobs/" + encodeURIComponent(job.jobId));
        if (progress) progress(result.progress || 0, result.message || "");
        if (result.status === "completed") return result.result;
        if (result.status === "failed") throw new Error(result.error || result.message || "Falha ao processar vídeo.");
        if (Date.now() - started > 3600000) throw new Error("Tempo limite excedido.");
        await new Promise(resolve => setTimeout(resolve, 650));
      }
    }

    async function runJob(path, body, progress) {
      return waitJob(
        await requestJson(path, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        }),
        progress
      );
    }

    async function runRawJob(path, blob, progress, cancelled = () => false) {
      if (!blob || !blob.size) throw new Error("Nenhum arquivo de vídeo disponível.");
      const signal = state.renderJob.active && state.renderJob.abort ? state.renderJob.abort.signal : undefined;
      return waitJob(
        await requestJson(path, {
          method: "POST",
          headers: { "Content-Type": "application/octet-stream" },
          body: blob,
          signal,
        }),
        progress,
        cancelled
      );
    }

    async function seekVideo(video, time) {
      if (video.readyState < 1) {
        video.load();
        await new Promise(r => { video.addEventListener("loadedmetadata", r, { once: true }); setTimeout(r, 4000); });
      }
      const dur = Number.isFinite(video.duration) && video.duration > 0 ? video.duration : time;
      const target = Math.max(0, Math.min(dur, time));
      if (!video.seeking && Math.abs(video.currentTime - target) < 0.05) return;
      await new Promise(resolve => {
        let doneFlag = false;
        const finish = () => {
          if (doneFlag) return;
          doneFlag = true;
          clearTimeout(timer);
          video.removeEventListener("seeked", finish);
          video.removeEventListener("error", finish);
          resolve();
        };
        const timer = setTimeout(finish, 3500);
        video.addEventListener("seeked", finish, { once: true });
        video.addEventListener("error", finish, { once: true });
        try { video.currentTime = target; } catch (_) { finish(); }
      });
    }

    function captionsForRange(start, end) {
      if (state.media.words && state.media.words.length) {
        const words = state.media.words.filter(w => w.end > start && w.start < end);
        const captions = [];
        let group = [];
        const flush = () => {
          if (!group.length) return;
          const a = Math.max(0, group[0].start - start);
          const b = Math.min(end - start, group[group.length - 1].end - start);
          if (b > a) captions.push({ start: a, end: b, text: group.map(w => w.text).join(" ").toUpperCase() });
          group = [];
        };
        for (const word of words) {
          if (group.length && (group.length >= 4 || word.start - group[group.length - 1].end > 0.7)) flush();
          group.push(word);
          if (/[.!?]$/.test(word.text)) flush();
        }
        flush();
        return captions;
      }
      return state.media.transcript
        .filter(c => c.end > start && c.start < end)
        .map(c => ({
          start: Math.max(0, c.start - start),
          end: Math.min(end - start, c.end - start),
          text: c.text,
        }))
        .filter(c => c.end > c.start);
    }

    function trackedPan(time, vw, vh, ratio) {
      const tracks = state.media.tracking || [];
      if (!tracks.length) return state.visual.panX;
      let i = tracks.findIndex(t => t.time >= time);
      if (i < 0) i = tracks.length - 1;
      const b = tracks[i], a = tracks[Math.max(0, i - 1)];
      const f = b.time === a.time ? 0 : Math.max(0, Math.min(1, (time - a.time) / (b.time - a.time)));
      const center = a.x + (b.x - a.x) * f;
      const crop = Math.min(vw, vh * ratio);
      const travel = vw - crop;
      return Math.max(-100, Math.min(100, travel ? ((center * vw - crop / 2) / travel) * 200 - 100 + state.visual.panX : 0));
    }

    const dropzone = document.querySelector(".dropzone");
    if (dropzone) {
      dropzone.addEventListener("dragover", e => { e.preventDefault(); });
      dropzone.addEventListener("drop", e => {
        e.preventDefault();
        handleLocalVideoFile({ target: { files: e.dataTransfer.files, value: "" } });
      });
    }
    const socialInput = document.getElementById("social-url-input");
    if (socialInput) {
      socialInput.addEventListener("change", e => resolveSocialLink(e.target.value));
      socialInput.addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); startViralAnalysis(); } });
    }
    window.addEventListener("pagehide", () => { stopPreview(); cancelMp4Render(); });

    setFrameMode("split");
    state.visual.fcSource = "top-center";
    document.getElementById("fc-source-select").value = "top-center";
    setWatermarkPosition("hidden");
    setCaptionsEnabled(true);
    refreshLibrary();
