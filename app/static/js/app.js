// STAR WARS COMMAND TERMINAL // Zoo CAD & Knowledge Controller

let currentEvalState = null;
let currentKCLCode = "";
let currentPartName = "Sheet Metal Support Bracket";

document.addEventListener("DOMContentLoaded", () => {
  initUploadBox();
  initActionButtons();
  streamLog("SYSTEM", "Initialized Live API Caller Terminal Logger. System ready.");
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
  // 1. Hide Dropzone immediately to prevent continuous file drops
  const dropzone = document.getElementById("dropzone");
  const fileCard = document.getElementById("uploadedFileCard");
  
  if (dropzone) dropzone.style.display = "none";
  if (fileCard) {
    fileCard.style.display = "flex";
    document.getElementById("fileNameText").textContent = `📄 ${file.name} (${(file.size/1024).toFixed(1)} KB)`;
  }

  streamLog("FILE_UPLOADER", `Received technical drawing file: '${file.name}'. Base64 encoding...`);
  streamLog("QWEN_VL_AGENT", "POST /api/upload-drawing -> Transmitting image to Qwen-VL Vision API...");

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
    currentPartName = data.title_block?.part_name || data.part_name || "Sheet Metal Support Bracket";

    streamLog("QWEN_VL_AGENT", `HTTP 200 OK -> Analysis complete. Antet Detected: '${currentPartName}'.`);

    // Stream trace logs
    if (data.agentic_trace) {
      data.agentic_trace.forEach(logMsg => streamLog("AGENT_TRACE", logMsg));
    }

    renderTitleBlock(data.title_block || {});
    renderEvaluationGatekeeper(data);

  } catch (err) {
    console.error(err);
    streamLog("ERROR", `Drawing inspection failure: ${err.message}`);
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

  streamLog("SYSTEM", "Reset file ingestion buffer. Ready for new file.");
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

  gatekeeperCard.style.display = "block";

  if (data.satisfies_requirements) {
    if (evalStatusPill) {
      evalStatusPill.className = "pill online";
      evalStatusPill.innerHTML = `<span class="dot"></span> COMPLETENESS: VERIFIED (100%)`;
    }
    submitAnswers();
  } else {
    if (evalStatusPill) {
      evalStatusPill.className = "pill";
      evalStatusPill.style.color = "var(--term-amber)";
      evalStatusPill.innerHTML = `⚠️ PARAMETERS MISSING // AUDIT REQUIRED`;
    }

    let html = `<div style="font-size: 0.8rem; color: var(--term-amber); margin-bottom: 0.65rem;">
      [!] Qwen Vision AI detected missing title block parameters. Please confirm:
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

  streamLog("KCL_SYNTHESIZER", "Synthesizing KittyCAD KCL definition based on verified parameters...");
  streamLog("ZOO_API", "POST /api/answer-questions -> Transmitting KCL payload to Zoo Engine API...");

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
    renderDFMAAgent(data.dfma_analysis);

    streamLog("ZOO_API", "HTTP 200 OK -> KCL Payload validated by Zoo Engine.");
    streamLog("DFMA_ENGINE", `Calculated Mass: ${data.dfma_analysis.mass_kg} kg | Cycle Time: ${data.dfma_analysis.total_cycle_time_min} min.`);

    // Automatically trigger Explode to display positions & operations
    handleExplodeAssembly();

  } catch (err) {
    console.error(err);
    streamLog("ZOO_ERROR", `KCL execution failed: ${err.message}`);
    alert("KCL Compilation error: " + err.message);
  }
}

function renderKCLCode(code) {
  const editor = document.getElementById("kclEditor");
  if (editor) {
    editor.textContent = code;
  }
}

function renderDFMAAgent(dfma) {
  const scoreBox = document.getElementById("dfmaScore");
  const metricsBox = document.getElementById("dfmaMetrics");

  if (scoreBox) {
    scoreBox.innerHTML = `
      <div>
        <div style="font-size: 0.75rem; color: var(--text-dim);">MANUFACTURABILITY INDEX</div>
        <div style="font-size: 0.85rem; font-weight: 700; color: var(--term-green);">${dfma.manufacturability_status}</div>
      </div>
      <div class="score-num">${dfma.dfma_score}%</div>
    `;
  }

  if (metricsBox) {
    metricsBox.innerHTML = `
      <div class="antet-card" style="border-color: var(--term-cyan);">
        <div class="antet-title" style="color: var(--term-cyan);">📊 ASSEMBLY KNOWLEDGE & METRICS SUMMARY</div>
        <div class="antet-grid">
          <div class="antet-item">Material: <strong>${dfma.material}</strong></div>
          <div class="antet-item">Density: <strong>${dfma.material_density_g_cm3} g/cm³</strong></div>
          <div class="antet-item">Calc. Volume: <strong>${dfma.volume_cm3} cm³</strong></div>
          <div class="antet-item">Calc. Mass: <strong>${dfma.mass_kg} kg (${dfma.mass_grams} g)</strong></div>
          <div class="antet-item">Total Cycle Time: <strong>${dfma.total_cycle_time_min} min (${dfma.total_cycle_time_hours} hrs)</strong></div>
          <div class="antet-item">Total Setup Time: <strong>${dfma.total_setup_time_min} min</strong></div>
        </div>
      </div>
    `;
  }
}

async function handleExplodeAssembly() {
  if (!currentKCLCode) {
    streamLog("WARNING", "No KCL code generated yet. Complete parameter verification first.");
    return;
  }

  streamLog("EXPLOADER_AGENT", "POST /api/explode-assembly -> Decomposing assembly into positions (Pozlar)...");

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
    renderPositionsList(data.parts || []);
    streamLog("EXPLOADER_AGENT", `HTTP 200 OK -> Successfully extracted ${data.sub_part_count} positions (Pozlar).`);

  } catch (err) {
    console.error(err);
    streamLog("EXPLODE_ERROR", `Explode operation failed: ${err.message}`);
    alert("Explode operation failed: " + err.message);
  }
}

function renderPositionsList(positions) {
  const container = document.getElementById("positionsContainer");
  if (!container) return;

  if (positions.length === 0) {
    container.innerHTML = `<div style="color: var(--text-dim);">Click 'Explode to Manufacture' to decompose assembly.</div>`;
    return;
  }

  let html = `<div style="font-size: 0.85rem; font-weight: 700; color: var(--term-amber); margin-bottom: 0.75rem; letter-spacing: 1px;">
    🧩 ASSEMBLY POSITIONS & MANUFACTURING OPERATIONS (${positions.length} ITEMS)
  </div>`;

  positions.forEach(pos => {
    const kclEscaped = encodeURIComponent(pos.kcl_code || "");
    
    html += `
      <div class="position-card">
        <div class="position-header">
          <div>
            <div class="position-title">${pos.full_name}</div>
            <div class="position-meta">${pos.type} • Dimensions: ${pos.dimensions} • Mass: ${pos.mass_g}g</div>
          </div>
          <button class="btn btn-secondary" onclick="openInZooStudio('${kclEscaped}')" style="padding: 0.4rem 0.8rem; font-size: 0.75rem;">
            🚀 OPEN IN ZOO.STUDIO
          </button>
        </div>

        <div style="font-size: 0.75rem; font-weight: 700; color: var(--term-cyan); margin-top: 0.25rem;">
          ⚙️ Manufacturing Routing Operations:
        </div>
        <div class="op-list">
          ${pos.operations ? pos.operations.map(op => `
            <div class="op-item">
              <span>Step ${op.step}: <strong>${op.op}</strong> (${op.machine})</span>
              <span style="color: var(--term-amber);">${op.time_sec}s</span>
            </div>
          `).join('') : '<div style="font-size: 0.7rem; color: var(--text-dim);">Standard laser cut & bend operations</div>'}
        </div>
      </div>
    `;
  });

  container.innerHTML = html;
}

function openInZooStudio(kclEncoded) {
  const kclCode = decodeURIComponent(kclEncoded);
  
  // Copy KCL code to user clipboard for quick paste in Zoo Studio
  navigator.clipboard.writeText(kclCode).then(() => {
    streamLog("ZOO_STUDIO", "KCL code copied to clipboard! Opening Zoo Studio (zoo.dev/studio)...");
  }).catch(err => {
    streamLog("ZOO_STUDIO", "Opening Zoo Studio (zoo.dev/studio)...");
  });

  window.open("https://zoo.dev/studio", "_blank");
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

function streamLog(caller, message) {
  const consoleBox = document.getElementById("footerTerminalLogs");
  if (!consoleBox) return;

  const timestamp = new Date().toLocaleTimeString();
  const line = document.createElement("div");
  line.className = "log-line";
  line.innerHTML = `
    <span class="log-time">[${timestamp}]</span>
    <span class="log-caller">[${caller}]</span>
    <span>${message}</span>
  `;
  consoleBox.appendChild(line);
  consoleBox.scrollTop = consoleBox.scrollHeight;
}
