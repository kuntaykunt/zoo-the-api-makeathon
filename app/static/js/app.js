// Zoo CAD Studio - Makeathon Interactive Controller

let currentEvalState = null;
let currentKCLCode = "";
let currentPartName = "Part";

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
  showStatus("Evaluating technical drawing via Qwen Vision AI...", "loading");

  const formData = new FormData();
  formData.append("file", file);

  try {
    const res = await fetch("/api/upload-drawing", {
      method: "POST",
      body: formData
    });

    if (!res.ok) throw new Error("Drawing analysis failed");

    const data = await res.json();
    currentEvalState = data;
    currentPartName = data.part_name || "Extracted_Part";

    renderEvaluationResult(data);

  } catch (err) {
    console.error(err);
    alert("Error uploading drawing: " + err.message);
  }
}

function renderEvaluationResult(data) {
  const gatekeeperCard = document.getElementById("gatekeeperCard");
  const questionsContainer = document.getElementById("questionsContainer");
  const evalStatusPill = document.getElementById("evalStatusPill");

  if (!gatekeeperCard) return;

  gatekeeperCard.style.display = "flex";

  if (data.satisfies_requirements) {
    evalStatusPill.className = "pill online";
    evalStatusPill.innerHTML = `<span class="dot"></span> 🟢 Completeness: YES (Full Info)`;
    
    // Automatically trigger KCL compilation
    submitAnswers();

  } else {
    evalStatusPill.className = "pill";
    evalStatusPill.style.color = "#f59e0b";
    evalStatusPill.innerHTML = `🔴 Completeness: NO (Missing Parameters)`;

    // Render interactive questions
    let html = `<div style="font-size: 0.75rem; color: #94a3b8; margin-bottom: 0.5rem;">
      Qwen-VL identified missing engineering parameters. Please complete below:
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
              <input type="text" class="input-field" id="q_${q.id}" value="${q.default_value || ''}" placeholder="e.g. 2.0">
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

  showStatus("Synthesizing KCL & Compiling in Zoo Engine...", "loading");

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

  } catch (err) {
    console.error(err);
    alert("KCL compilation error: " + err.message);
  }
}

function renderKCLCode(code) {
  const editor = document.getElementById("kclEditor");
  if (editor) {
    editor.textContent = code;
  }
}

function renderZooCompileResult(zooRes) {
  const renderImg = document.getElementById("viewportImg");
  const statsBox = document.getElementById("modelStats");

  if (renderImg && zooRes.render_url) {
    renderImg.src = zooRes.render_url + "?t=" + new Date().getTime();
  }

  if (statsBox && zooRes.model_stats) {
    const s = zooRes.model_stats;
    statsBox.innerHTML = `
      <div class="stat-chip">Volume: <strong>${s.volume_cm3} cm³</strong></div>
      <div class="stat-chip">Mass: <strong>${s.mass_grams} g</strong></div>
      <div class="stat-chip">Bounding Box: <strong>${s.bounding_box_mm.x}x${s.bounding_box_mm.y}x${s.bounding_box_mm.z} mm</strong></div>
    `;
  }
}

function renderDFMAAgent(dfma) {
  const scoreBox = document.getElementById("dfmaScore");
  const warningsBox = document.getElementById("dfmaWarnings");
  const opsBox = document.getElementById("dfmaOps");

  if (scoreBox) {
    scoreBox.innerHTML = `
      <div>
        <div style="font-size: 0.75rem; color: #94a3b8;">Manufacturability Score</div>
        <div style="font-size: 0.8rem; font-weight: 600; color: #f8fafc;">${dfma.manufacturability_status}</div>
      </div>
      <div class="score-num">${dfma.dfma_score}%</div>
    `;
  }

  if (warningsBox && dfma.dfma_warnings) {
    warningsBox.innerHTML = dfma.dfma_warnings.map(w => `
      <div class="stat-chip" style="border-left: 3px solid ${w.severity === 'warning' ? '#f59e0b' : '#10b981'}; width: 100%;">
        <strong>${w.rule}:</strong> ${w.message}
      </div>
    `).join('');
  }

  if (opsBox && dfma.manufacturing_operations) {
    opsBox.innerHTML = dfma.manufacturing_operations.map(op => `
      <div class="op-card">
        <div class="op-header">
          <span>Step ${op.step}: ${op.operation}</span>
          <span style="color: #38bdf8;">${op.estimated_time_sec}s</span>
        </div>
        <div class="op-desc">${op.description}</div>
        <div class="op-meta">🛠️ Machine: ${op.machine}</div>
      </div>
    `).join('');
  }
}

async function handleExplodeAssembly() {
  if (!currentKCLCode) return;

  showStatus("Decomposing assembly into manufacturable parts...", "loading");

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

  } catch (err) {
    console.error(err);
    alert("Explode operation failed: " + err.message);
  }
}

function renderExplodedParts(data) {
  const container = document.getElementById("explodedPartsContainer");
  if (!container) return;

  container.style.display = "flex";
  
  let html = `<div style="font-size: 0.8rem; font-weight: 700; color: #38bdf8; margin-bottom: 0.5rem;">
    💥 Exploded Sub-parts (${data.sub_part_count} items)
  </div>`;

  data.parts.forEach(p => {
    html += `
      <div class="part-item">
        <div>
          <strong style="color: #f8fafc;">${p.part_name}</strong>
          <div style="font-size: 0.65rem; color: #94a3b8;">${p.type} • ${p.dimensions}</div>
        </div>
        <span class="stat-chip" style="border-color: #10b981; color: #10b981;">${p.status}</span>
      </div>
    `;
  });

  container.innerHTML = html;
}

function initActionButtons() {
  const submitAnswersBtn = document.getElementById("submitAnswersBtn");
  if (submitAnswersBtn) {
    submitAnswersBtn.addEventListener("click", submitAnswers);
  }

  const explodeBtn = document.getElementById("explodeBtn");
  if (explodeBtn) {
    explodeBtn.addEventListener("click", handleExplodeAssembly);
  }
}

function showStatus(msg, type) {
  console.log(`[Status: ${type}] ${msg}`);
}
