// STAR WARS COMMAND TERMINAL // Zoo CAD Studio Controller

let currentEvalState = null;
let currentKCLCode = "";
let currentPartName = "Part";
let currentUploadedFileName = "";

document.addEventListener("DOMContentLoaded", () => {
  initUploadBox();
  initActionButtons();
});

function initUploadBox() {
  const dropzone = document.getElementById("dropzone");
  const fileInput = document.getElementById("fileInput");

  if (!dropzone || !fileInput) return;

  dropzone.addEventListener("click", () => fileInput.click());

  dropzone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropzone.classList.add("dragover");
  });

  dropzone.addEventListener("dragleave", () => {
    dropzone.classList.remove("dragover");
  });

  dropzone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropzone.classList.remove("dragover");
    if (e.dataTransfer.files.length > 0) {
      handleFileUpload(e.dataTransfer.files[0]);
    }
  });

  fileInput.addEventListener("change", (e) => {
    if (e.target.files.length > 0) {
      handleFileUpload(e.target.files[0]);
    }
  });
}

async function handleFileUpload(file) {
  currentUploadedFileName = file.name;

  // 1. Hide Dropzone immediately to prevent continuous file drops
  const dropzone = document.getElementById("dropzone");
  const fileCard = document.getElementById("uploadedFileCard");
  
  if (dropzone) dropzone.style.display = "none";
  if (fileCard) {
    fileCard.style.display = "flex";
    document.getElementById("fileNameText").textContent = `📄 ${file.name} (${(file.size/1024).toFixed(1)} KB)`;
  }

  showTerminalLog("SYSTEM: Uploading technical drawing file...", "info");
  showTerminalLog("AGENT: Invoking Qwen-VL Technical Inspection Agent v2.4...", "info");

  const formData = new FormData();
  formData.append("file", file);

  try {
    const res = await fetch("/api/upload-drawing", {
      method: "POST",
      body: formData
    });

    if (!res.ok) throw new Error("Drawing inspection failed.");

    const data = await res.json();
    currentEvalState = data;
    currentPartName = data.title_block?.part_name || data.part_name || "CAD_Part";

    // 2. Render Agentic Trace & Title Block (Antet)
    renderAgenticTrace(data.agentic_trace || []);
    renderTitleBlock(data.title_block || {});
    renderEvaluationGatekeeper(data);

  } catch (err) {
    console.error(err);
    showTerminalLog(`ERROR: ${err.message}`, "error");
    alert("Error inspecting drawing: " + err.message);
  }
}

function resetFileUpload() {
  const dropzone = document.getElementById("dropzone");
  const fileCard = document.getElementById("uploadedFileCard");
  const gatekeeperCard = document.getElementById("gatekeeperCard");
  const antetCard = document.getElementById("antetCard");

  if (dropzone) dropzone.style.display = "block";
  if (fileCard) fileCard.style.display = "none";
  if (gatekeeperCard) gatekeeperCard.style.display = "none";
  if (antetCard) antetCard.style.display = "none";

  showTerminalLog("SYSTEM: Reset file input buffer.", "info");
}

function renderAgenticTrace(traceLogs) {
  const consoleBox = document.getElementById("terminalConsole");
  if (!consoleBox) return;

  consoleBox.innerHTML = "";
  traceLogs.forEach(log => {
    const line = document.createElement("div");
    line.className = "terminal-line";
    line.textContent = log;
    consoleBox.appendChild(line);
  });
  consoleBox.scrollTop = consoleBox.scrollHeight;
}

function renderTitleBlock(tb) {
  const antetCard = document.getElementById("antetCard");
  const antetGrid = document.getElementById("antetGrid");

  if (!antetCard || !antetGrid) return;

  antetCard.style.display = "block";
  antetGrid.innerHTML = `
    <div class="antet-item">Part Title: <strong>${tb.part_name || 'N/A'}</strong></div>
    <div class="antet-item">DWG No: <strong>${tb.drawing_number || 'N/A'}</strong></div>
    <div class="antet-item">Revision: <strong>${tb.revision || 'A'}</strong></div>
    <div class="antet-item">Scale: <strong>${tb.scale || '1:1'}</strong></div>
    <div class="antet-item">Material: <strong>${tb.material_spec || 'N/A'}</strong></div>
    <div class="antet-item">Tolerances: <strong>${tb.tolerances || 'ISO 2768-m'}</strong></div>
  `;
}

function renderEvaluationGatekeeper(data) {
  const gatekeeperCard = document.getElementById("gatekeeperCard");
  const questionsContainer = document.getElementById("questionsContainer");
  const evalStatusPill = document.getElementById("evalStatusPill");

  if (!gatekeeperCard) return;

  gatekeeperCard.style.display = "flex";

  if (data.satisfies_requirements) {
    evalStatusPill.className = "pill online";
    evalStatusPill.innerHTML = `<span class="dot"></span> COMPLETENESS: VERIFIED (100%)`;
    
    // Auto synthesize KCL
    submitAnswers();

  } else {
    evalStatusPill.className = "pill";
    evalStatusPill.style.color = "var(--term-amber)";
    evalStatusPill.innerHTML = `⚠️ PARAMETERS MISSING // AUDIT REQUIRED`;

    let html = `<div style="font-size: 0.75rem; color: var(--term-amber); margin-bottom: 0.5rem;">
      [!] Qwen Vision AI detected missing title block parameters. Please verify/complete:
    </div>`;

    if (data.questions && data.questions.length > 0) {
      data.questions.forEach(q => {
        html += `
          <div class="question-group">
            <label class="question-label">${q.question}</label>
            ${q.options ? `
              <select class="input-field" id="q_${q.id}">
                ${q.options.map(opt => `<option value="${opt}" ${opt === q.default_value ? 'selected' : ''}>${opt}</option>`).join('')}
              </select>
            ` : `
              <input type="text" class="input-field" id="q_${q.id}" value="${q.default_value || ''}">
            `}
          </div>
        `;
      });
    }

    questionsContainer.innerHTML = html;
  }
}

async function submitAnswers() {
  const userAnswers = {};
  
  if (currentEvalState && currentEvalState.questions) {
    currentEvalState.questions.forEach(q => {
      const el = document.getElementById(`q_${q.id}`);
      if (el) {
        userAnswers[q.id] = el.value;
      }
    });
  }

  showTerminalLog("SYSTEM: Synthesizing KittyCAD Language (KCL) Code...", "info");
  showTerminalLog("ZOO_ENGINE: Transmitting KCL payload to api.zoo.dev...", "info");

  try {
    const res = await fetch("/api/answer-questions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        initial_eval: currentEvalState || {},
        user_answers: userAnswers
      })
    });

    const data = await res.json();
    
    currentKCLCode = data.kcl_code;
    renderKCLCode(data.kcl_code);
    renderZooCompileResult(data.zoo_compile);
    renderDFMAAgent(data.dfma_analysis);

    document.getElementById("explodeBtn").style.display = "inline-flex";
    showTerminalLog("SYSTEM: 3D CAD Compiled & DFMA Operations Evaluated Successfully.", "info");

  } catch (err) {
    console.error(err);
    showTerminalLog(`ZOO_ERROR: ${err.message}`, "error");
    alert("KCL Compilation error: " + err.message);
  }
}

function renderKCLCode(code) {
  const editor = document.getElementById("kclEditor");
  if (editor) {
    editor.textContent = code;
  }
}

function renderZooCompileResult(zooRes) {
  const emptyNotice = document.getElementById("emptyViewportNotice");
  const renderImg = document.getElementById("viewportImg");
  const statsBox = document.getElementById("modelStats");

  // Show 3D render only when compiled
  if (emptyNotice) emptyNotice.style.display = "none";
  if (renderImg) {
    renderImg.style.display = "block";
    renderImg.src = (zooRes.render_url || "/static/renders/sample_3d_render.png") + "?t=" + new Date().getTime();
  }

  if (statsBox && zooRes.model_stats) {
    const s = zooRes.model_stats;
    statsBox.innerHTML = `
      <div class="stat-chip">Volume: <strong>${s.volume_cm3} cm³</strong></div>
      <div class="stat-chip">Mass: <strong>${s.mass_grams} g</strong></div>
      <div class="stat-chip">Bounding: <strong>${s.bounding_box_mm.x}x${s.bounding_box_mm.y}x${s.bounding_box_mm.z} mm</strong></div>
    `;
  }
}

function renderDFMAAgent(dfma) {
  const scoreBox = document.getElementById("dfmaScore");
  const metricsBox = document.getElementById("dfmaMetrics");
  const warningsBox = document.getElementById("dfmaWarnings");
  const opsBox = document.getElementById("dfmaOps");

  if (scoreBox) {
    scoreBox.innerHTML = `
      <div>
        <div style="font-size: 0.7rem; color: var(--text-dim);">MANUFACTURABILITY SCORE</div>
        <div style="font-size: 0.75rem; font-weight: 700; color: var(--term-green);">${dfma.manufacturability_status}</div>
      </div>
      <div class="score-num">${dfma.dfma_score}%</div>
    `;
  }

  if (metricsBox) {
    metricsBox.innerHTML = `
      <div class="antet-card" style="border-color: var(--term-cyan);">
        <div class="antet-title" style="color: var(--term-cyan);">📊 DFMA GEOMETRY & MATERIAL METRICS</div>
        <div class="antet-grid">
          <div class="antet-item">Material: <strong>${dfma.material}</strong></div>
          <div class="antet-item">Density: <strong>${dfma.material_density_g_cm3} g/cm³</strong></div>
          <div class="antet-item">Calc. Volume: <strong>${dfma.volume_cm3} cm³</strong></div>
          <div class="antet-item">Calc. Mass: <strong>${dfma.mass_kg} kg (${dfma.mass_grams} g)</strong></div>
          <div class="antet-item">Total Cycle: <strong>${dfma.total_cycle_time_min} min (${dfma.total_cycle_time_hours} hrs)</strong></div>
          <div class="antet-item">Total Setup: <strong>${dfma.total_setup_time_min} min</strong></div>
        </div>
      </div>
    `;
  }

  if (warningsBox && dfma.dfma_warnings) {
    warningsBox.innerHTML = dfma.dfma_warnings.map(w => `
      <div class="stat-chip" style="border-color: ${w.severity === 'warning' ? 'var(--term-amber)' : 'var(--term-green)'}; width: 100%;">
        <strong>${w.rule}:</strong> ${w.message}
      </div>
    `).join('');
  }

  if (opsBox && dfma.manufacturing_operations) {
    opsBox.innerHTML = dfma.manufacturing_operations.map(op => `
      <div class="op-card">
        <div class="op-header">
          <span>STEP ${op.step}: ${op.operation}</span>
          <span style="color: var(--term-amber);">${op.process_time_sec}s (Setup: ${op.setup_time_min}m)</span>
        </div>
        <div class="op-desc">${op.description}</div>
        <div class="op-meta">🛠️ Machine: ${op.machine} | Tool: ${op.tooling}</div>
      </div>
    `).join('');
  }
}

async function handleExplodeAssembly() {
  if (!currentKCLCode) return;

  showTerminalLog("SYSTEM: Exploding assembly drawing into individual sub-parts...", "info");

  try {
    const res = await fetch("/api/explode-assembly", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        kcl_code: currentKCLCode,
        part_name: currentPartName
      })
    });

    const data = await res.json();
    renderExplodedParts(data);
    showTerminalLog(`SYSTEM: Assembly exploded into ${data.sub_part_count} individual manufacturable parts.`, "info");

  } catch (err) {
    console.error(err);
    showTerminalLog(`EXPLODE_ERROR: ${err.message}`, "error");
    alert("Explode operation failed: " + err.message);
  }
}

function renderExplodedParts(data) {
  const container = document.getElementById("explodedPartsContainer");
  if (!container) return;

  container.style.display = "flex";
  
  let html = `<div style="font-size: 0.8rem; font-weight: 700; color: var(--term-amber); margin-bottom: 0.5rem; letter-spacing: 1px;">
    💥 EXPLODED MANUFACTURING SUB-PARTS (${data.sub_part_count} ITEMS)
  </div>`;

  data.parts.forEach(p => {
    html += `
      <div class="op-card" style="border-left-color: var(--term-amber);">
        <div class="op-header">
          <strong style="color: var(--text-main);">${p.part_name}</strong>
          <span style="color: var(--term-green);">${p.status}</span>
        </div>
        <div class="op-desc">${p.type} • Dimensions: ${p.dimensions} • Mass: ${p.mass_g}g</div>
      </div>
    `;
  });

  container.innerHTML = html;
}

function initActionButtons() {
  const resetBtn = document.getElementById("resetFileBtn");
  if (resetBtn) {
    resetBtn.addEventListener("click", resetFileUpload);
  }

  const submitAnswersBtn = document.getElementById("submitAnswersBtn");
  if (submitAnswersBtn) {
    submitAnswersBtn.addEventListener("click", submitAnswers);
  }

  const explodeBtn = document.getElementById("explodeBtn");
  if (explodeBtn) {
    explodeBtn.addEventListener("click", handleExplodeAssembly);
  }
}

function showTerminalLog(msg, type) {
  const consoleBox = document.getElementById("terminalConsole");
  if (!consoleBox) return;

  const line = document.createElement("div");
  line.className = "terminal-line";
  if (type === "error") line.style.color = "var(--term-red)";
  line.textContent = `[${new Date().toLocaleTimeString()}] ${msg}`;
  consoleBox.appendChild(line);
  consoleBox.scrollTop = consoleBox.scrollHeight;
}
