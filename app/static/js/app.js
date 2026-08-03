// STAR WARS COMMAND TERMINAL // Agent Harness & Resizable Terminal Controller

let currentEvalState = null;
let currentKCLCode = "";
let currentPartName = "Sheet Metal Support Bracket";
let isZooModelVerified = false;

document.addEventListener("DOMContentLoaded", () => {
  initUploadBox();
  initActionButtons();
  initResizableTerminal();
  
  const explodeBtn = document.getElementById("explodeBtn");
  if (explodeBtn) explodeBtn.style.display = "none";

  streamLog("AGENT_HARNESS", "Initialized Agentic Loop Engine v2.4.");
  streamLog("AGENT_HARNESS", "GATING STATUS: 'EXPLODE TO MANUFACTURE' capability LOCKED.");
  streamLog("AGENT_HARNESS", "Prerequisites: 1. Drawing Inspection -> 2. Title Block Audit -> 3. Zoo API Verification.");
});

function initResizableTerminal() {
  const handle = document.getElementById("terminalResizeHandle");
  const terminal = document.getElementById("footerTerminal");
  if (!handle || !terminal) return;

  let isDragging = false;
  let startY = 0;
  let startHeight = 160;

  handle.addEventListener("mousedown", (e) => {
    isDragging = true;
    startY = e.clientY;
    startHeight = terminal.offsetHeight;
    document.body.style.userSelect = "none";
  });

  document.addEventListener("mousemove", (e) => {
    if (!isDragging) return;
    const dy = startY - e.clientY;
    const newHeight = Math.max(90, Math.min(window.innerHeight * 0.8, startHeight + dy));
    terminal.style.height = `${newHeight}px`;
    document.body.style.paddingBottom = `${newHeight + 10}px`;
  });

  document.addEventListener("mouseup", () => {
    if (isDragging) {
      isDragging = false;
      document.body.style.userSelect = "";
    }
  });
}

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
  const dropzone = document.getElementById("dropzone");
  const fileCard = document.getElementById("uploadedFileCard");
  const resetBtn = document.getElementById("resetFileBtn");
  
  if (dropzone) dropzone.style.display = "none";
  if (fileCard) {
    fileCard.style.display = "flex";
    document.getElementById("fileNameText").textContent = `📄 ${file.name} (${(file.size/1024).toFixed(1)} KB)`;
  }
  
  if (resetBtn) resetBtn.style.display = "none";

  streamLog("HARNESS_LOOP", "[STEP 1/4] Normalizing image buffer & executing Qwen-VL Vision Inspection...");
  streamLog("QWEN_VL_AGENT", `POST /api/upload-drawing -> Transmitting '${file.name}' to Qwen-VL Vision API...`);

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
    currentPartName = data.title_block?.part_name || data.part_name || file.name.split('.')[0];

    if (data.error) {
      streamLog("QWEN_ERROR", data.message);
    } else if (data.raw_qwen_response) {
      streamLog("QWEN_VL_RESPONSE", data.raw_qwen_response);
    }

    streamLog("QWEN_VL_AGENT", `Analysis Complete -> Scanned Part Title: '${currentPartName}' (DWG: ${data.title_block?.drawing_number || 'N/A'}).`);

    if (data.agentic_trace) {
      data.agentic_trace.forEach(logMsg => streamLog("AGENT_TRACE", logMsg));
    }

    renderTitleBlock(data.title_block || {});
    renderEvaluationGatekeeper(data);
    renderInferenceSummary(data);

  } catch (err) {
    console.error(err);
    streamLog("ERROR", `Drawing inspection failure: ${err.message}`);
    alert("Error inspecting drawing: " + err.message);
  }
}

function resetFileUpload() {
  console.log("[System] START FRESH Triggered...");
  const dropzone = document.getElementById("dropzone");
  const fileInput = document.getElementById("fileInput");
  const fileCard = document.getElementById("uploadedFileCard");
  const gatekeeperCard = document.getElementById("gatekeeperCard");
  const antetCard = document.getElementById("antetCard");
  const explodeBtn = document.getElementById("explodeBtn");
  const positionsContainer = document.getElementById("positionsContainer");
  const inferenceContent = document.getElementById("inferenceContent");

  if (fileInput) fileInput.value = "";
  if (dropzone) dropzone.style.display = "block";
  if (fileCard) fileCard.style.display = "none";
  if (gatekeeperCard) gatekeeperCard.style.display = "none";
  if (antetCard) antetCard.style.display = "none";
  if (explodeBtn) explodeBtn.style.display = "none";

  if (inferenceContent) {
    inferenceContent.innerHTML = `
      <div style="color: var(--text-dim); font-size: 0.8rem;">
        Upload a drawing to execute Qwen Vision AI & Zoo Agent classification...
      </div>
    `;
  }

  if (positionsContainer) {
    positionsContainer.innerHTML = `
      <div style="color: var(--text-dim); font-size: 0.85rem; text-align: center; padding: 2rem; border: 1px dashed var(--term-border);">
        Ingest a drawing and complete parameter verification to unlock <strong>'EXPLODE TO MANUFACTURE'</strong> capability.
      </div>
    `;
  }

  isZooModelVerified = false;
  currentEvalState = null;
  currentKCLCode = "";

  streamLog("AGENT_HARNESS", "START FRESH: State buffer cleared. Ingestion box re-activated.");
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

function renderInferenceSummary(data) {
  const container = document.getElementById("inferenceContent");
  if (!container) return;

  const isAssembly = data.is_assembly !== false;
  const classificationText = isAssembly ? "ASSEMBLY (Multi-Part Drawing Component)" : "SINGLE PART COMPONENT";
  const statusColor = isAssembly ? "var(--term-amber)" : "var(--term-green)";

  container.innerHTML = `
    <div style="font-size: 0.85rem; font-weight: 700; color: ${statusColor}; margin-bottom: 0.5rem;">
      🔍 Classification: ${classificationText}
    </div>
    <div style="font-size: 0.8rem; color: var(--text-main); margin-bottom: 0.4rem;">
      <strong>CAD Inference Summary:</strong> ${data.detected_parameters?.overall_dimensions || 'Dimensions detected from projections.'}
    </div>
    <div style="font-size: 0.75rem; color: var(--text-dim); line-height: 1.4; background: rgba(0,0,0,0.4); padding: 0.5rem; border-left: 2px solid var(--term-cyan);">
      🤖 <strong>Zoo Agent API Summary:</strong> Evaluated drawing geometry. Identified sub-component boundaries & manufacturing constraints. Ready to compile KCL definitions for each position (Poz).
    </div>
  `;
}

function renderEvaluationGatekeeper(data) {
  const gatekeeperCard = document.getElementById("gatekeeperCard");
  const questionsContainer = document.getElementById("questionsContainer");
  const evalStatusPill = document.getElementById("evalStatusPill");

  if (!gatekeeperCard) return;

  gatekeeperCard.style.display = "block";

  if (data.error) {
    if (evalStatusPill) {
      evalStatusPill.className = "pill";
      evalStatusPill.style.color = "var(--term-red)";
      evalStatusPill.innerHTML = `❌ QWEN API RESPONSE ALERT`;
    }
    questionsContainer.innerHTML = `
      <div style="background: rgba(255, 42, 109, 0.1); border: 1px solid var(--term-red); padding: 0.75rem; color: var(--term-red); font-size: 0.8rem; margin-bottom: 0.5rem;">
        <strong>API Response:</strong> ${data.message}
      </div>
      <div style="font-size: 0.75rem; color: var(--text-dim);">
        Please verify parameters manually below to continue:
      </div>
    `;
    return;
  }

  if (data.satisfies_requirements) {
    if (evalStatusPill) {
      evalStatusPill.className = "pill online";
      evalStatusPill.innerHTML = `<span class="dot"></span> COMPLETENESS: VERIFIED (100%)`;
    }
    streamLog("HARNESS_LOOP", "[STEP 2/4] Title block parameters 100% complete. Proceeding to Zoo Agent API check...");
    submitAnswers();
  } else {
    if (evalStatusPill) {
      evalStatusPill.className = "pill";
      evalStatusPill.style.color = "var(--term-amber)";
      evalStatusPill.innerHTML = `⚠️ AUDIT ALERT // MISSING PARAMETERS`;
    }

    streamLog("HARNESS_LOOP", "[STEP 2/4] Audit Alert: Parameters missing. Requesting user input verification...");

    let html = `<div style="font-size: 0.8rem; color: var(--term-amber); margin-bottom: 0.65rem;">
      [!] Confirm missing technical parameters to proceed:
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

  streamLog("KCL_SYNTHESIZER", "Synthesizing KittyCAD KCL code from verified parameters...");
  streamLog("HARNESS_LOOP", "[STEP 3/4] Transmitting KCL payload to Zoo Engine API (api.zoo.dev)...");
  streamLog("ZOO_ENGINE_API", "POST /api/answer-questions -> Verifying geometry readiness via Zoo Agent API...");

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
    renderDFMAAgent(data.dfma_analysis);

    // Update Zoo Agent Summary
    if (data.zoo_verification?.summary) {
      const inferenceContainer = document.getElementById("inferenceContent");
      if (inferenceContainer) {
        const isAssembly = currentEvalState?.is_assembly !== false;
        inferenceContainer.innerHTML = `
          <div style="font-size: 0.85rem; font-weight: 700; color: var(--term-amber); margin-bottom: 0.5rem;">
            🔍 Classification: ${isAssembly ? "ASSEMBLY (Multi-Part Drawing Component)" : "SINGLE PART COMPONENT"}
          </div>
          <div style="font-size: 0.8rem; color: var(--text-main); margin-bottom: 0.4rem;">
            <strong>Material:</strong> ${data.material} • <strong>Thickness:</strong> ${data.thickness_mm}mm
          </div>
          <div style="font-size: 0.75rem; color: var(--term-green); line-height: 1.4; background: rgba(5, 255, 161, 0.05); padding: 0.5rem; border: 1px solid rgba(5, 255, 161, 0.3);">
            ✅ <strong>Zoo Agent API Verification:</strong> ${data.zoo_verification.summary}
          </div>
        `;
      }
    }

    if (data.model_ready && data.zoo_verification?.model_ready) {
      isZooModelVerified = true;
      streamLog("ZOO_ENGINE_API", `HTTP 200 OK -> Geometry Verification SUCCESS: ${data.zoo_verification.compile_status}`);
      streamLog("HARNESS_LOOP", "[STEP 4/4] Zoo Engine model verification CONFIRMED! Unlocking 'EXPLODE TO MANUFACTURE' capability.");

      const explodeBtn = document.getElementById("explodeBtn");
      if (explodeBtn) {
        explodeBtn.style.display = "inline-flex";
        explodeBtn.style.boxShadow = "0 0 15px var(--term-amber)";
      }

      handleExplodeAssembly();

    } else {
      isZooModelVerified = false;
      streamLog("ZOO_ENGINE_API", "HTTP 400 ERROR -> Zoo Engine compile unverified.");
    }

  } catch (err) {
    console.error(err);
    streamLog("ZOO_ERROR", `KCL compilation error: ${err.message}`);
    alert("KCL Compilation error: " + err.message);
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
  if (!isZooModelVerified) {
    streamLog("AGENT_HARNESS", "REJECTED: Explode capability is LOCKED until Zoo Engine API model verification completes!");
    alert("Explode is locked until Zoo Engine API verifies 3D geometry compilation.");
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
    container.innerHTML = `<div style="color: var(--text-dim);">Awaiting Explode command...</div>`;
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
  
  navigator.clipboard.writeText(kclCode).then(() => {
    streamLog("ZOO_STUDIO", "KCL snippet copied to clipboard! Launching Zoo Studio (zoo.dev/studio)...");
  }).catch(err => {
    streamLog("ZOO_STUDIO", "Launching Zoo Studio (zoo.dev/studio)...");
  });

  window.open("https://zoo.dev/studio", "_blank");
}

function initActionButtons() {
  const startFreshBtn = document.getElementById("startFreshBtn");
  if (startFreshBtn) {
    startFreshBtn.addEventListener("click", resetFileUpload);
  }

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
