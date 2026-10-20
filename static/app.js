/**
 * AI Data Insight Builder - Frontend Logic (Vanilla JS)
 * 규칙: 지정된 태그 형식의 콘솔 로그를 반드시 출력하며, API Key나 CSV 원본은 절대 로깅하지 않습니다.
 */

// 전역 차트 인스턴스 보관용
let currentChartInstance = null;
let selectedFile = null;

document.addEventListener("DOMContentLoaded", () => {
    console.log("[PAGE] 페이지 로드 완료");
    initHealthCheck();
    initFileUpload();
    initEventHandlers();
});

/* -------------------------------------------------------------
   0. 서버 상태 점검 (/health)
------------------------------------------------------------- */
async function initHealthCheck() {
    const healthBadge = document.getElementById("healthBadge");
    const modelBadge = document.getElementById("modelBadge");

    try {
        const res = await fetch("/health");
        const data = await res.json();
        
        if (data.status === "ok") {
            if (data.api_key_configured) {
                healthBadge.className = "badge badge-ok";
                healthBadge.textContent = "● 서버 정상 (API Key 연결됨)";
            } else {
                healthBadge.className = "badge badge-error";
                healthBadge.textContent = "▲ API Key 미설정 (.env 확인)";
            }
            modelBadge.textContent = `Model: ${data.model}`;
        }
    } catch (err) {
        console.error("[ERROR] 서버 헬스체크 실패:", err.message);
        healthBadge.className = "badge badge-error";
        healthBadge.textContent = "✕ 서버 오프라인";
    }
}

/* -------------------------------------------------------------
   1. 파일 드래그 앤 드롭 및 선택 처리
------------------------------------------------------------- */
function initFileUpload() {
    const dropArea = document.getElementById("dropArea");
    const fileInput = document.getElementById("csvFileInput");
    const selectedFileName = document.getElementById("selectedFileName");
    const inspectBtn = document.getElementById("inspectBtn");

    // 드래그 앤 드롭 이벤트
    ["dragenter", "dragover"].forEach(evt => {
        dropArea.addEventListener(evt, (e) => {
            e.preventDefault();
            e.stopPropagation();
            dropArea.classList.add("dragover");
        });
    });

    ["dragleave", "drop"].forEach(evt => {
        dropArea.addEventListener(evt, (e) => {
            e.preventDefault();
            e.stopPropagation();
            dropArea.classList.remove("dragover");
        });
    });

    dropArea.addEventListener("drop", (e) => {
        const files = e.dataTransfer.files;
        if (files && files.length > 0) {
            handleFileSelect(files[0]);
        }
    });

    fileInput.addEventListener("change", (e) => {
        if (e.target.files && e.target.files.length > 0) {
            handleFileSelect(e.target.files[0]);
        }
    });

    function handleFileSelect(file) {
        if (!file.name.toLowerCase().endsWith(".csv")) {
            console.error("[ERROR] 확장자 오류: CSV 파일이 아닙니다.");
            alert("CSV 파일(.csv)만 업로드할 수 있습니다.");
            return;
        }

        selectedFile = file;
        selectedFileName.textContent = `선택된 파일: ${file.name} (${formatBytes(file.size)})`;
        inspectBtn.disabled = false;
        console.log(`[UPLOAD] 파일 선택: ${file.name} (${file.size} bytes)`);
    }
}

/* -------------------------------------------------------------
   2. 이벤트 핸들러 바인딩
------------------------------------------------------------- */
function initEventHandlers() {
    const uploadForm = document.getElementById("uploadForm");
    const suggestBtn = document.getElementById("suggestBtn");
    const manualRunBtn = document.getElementById("manualRunBtn");
    const explainBtn = document.getElementById("explainBtn");

    // 1) /inspect 제출
    uploadForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        if (!selectedFile) return;
        await requestInspect(selectedFile);
    });

    // 2) /suggest 요청
    suggestBtn.addEventListener("click", async () => {
        await requestSuggest();
    });

    // 3) 수동 /run 요청
    manualRunBtn.addEventListener("click", async () => {
        const tool = document.getElementById("manualToolSelect").value;
        const refPeriod = document.getElementById("manualRefPeriod").value.trim();
        const excludeAggs = document.getElementById("manualExcludeAggs").checked;

        const params = {
            reference_period: refPeriod,
            exclude_aggregates: excludeAggs
        };
        await executeTool(tool, params);
    });

    // 4) /explain 요청
    explainBtn.addEventListener("click", async () => {
        const selectedMode = document.querySelector('input[name="explainMode"]:checked').value;
        await requestExplain(selectedMode);
    });

    // 5) 후속 질문 (Q&A) 제출
    const qaForm = document.getElementById("qaForm");
    const qaInput = document.getElementById("qaInput");
    qaForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const questionText = qaInput.value.trim();
        if (!questionText) return;
        qaInput.value = "";
        await requestAsk(questionText);
    });

    // 6) 자연어 그래프 생성 요청 (/query)
    const nlForm = document.getElementById("nlQueryForm");
    const nlInput = document.getElementById("nlQueryInput");
    nlForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const promptText = nlInput.value.trim();
        if (!promptText) return;
        await requestNaturalQuery(promptText);
    });

    // 자연어 추천 칩 클릭 이벤트
    document.querySelectorAll(".nl-chip").forEach(chip => {
        chip.addEventListener("click", () => {
            const prompt = chip.getAttribute("data-prompt");
            nlInput.value = prompt;
            requestNaturalQuery(prompt);
        });
    });
}

/* -------------------------------------------------------------
   3. 진단 요청 API (/inspect)
------------------------------------------------------------- */
async function requestInspect(file) {
    const inspectBtn = document.getElementById("inspectBtn");
    const uploadSpinner = document.getElementById("uploadSpinner");
    const diagSection = document.getElementById("diagnosticsSection");

    inspectBtn.disabled = true;
    uploadSpinner.classList.remove("hidden");
    console.log("[INSPECT] 진단 요청 시작");

    const formData = new FormData();
    formData.append("file", file);

    try {
        const res = await fetch("/inspect", {
            method: "POST",
            body: formData
        });

        const data = await res.json();
        if (!res.ok) {
            throw new Error(data.error || "진단 중 오류가 발생했습니다.");
        }

        const diag = data.diagnostics || {};
        console.log(`[INSPECT] 진단 응답 수신: 행 수=${diag.rows}, 열 수=${diag.columns}, 경고 수=${diag.warnings?.length || 0}`);

        // UI 메타데이터 업데이트
        document.getElementById("metaFileName").textContent = `${data.filename} (${formatBytes(data.file_size)})`;
        document.getElementById("metaEncoding").textContent = `${data.encoding} (상단 ${data.skipped_rows}줄 스킵)`;
        document.getElementById("metaShape").textContent = `${diag.rows}행 × ${diag.columns}열`;
        
        const recYear = diag.recommended_reference_year || "감지안됨";
        document.getElementById("metaRecommendedYear").textContent = recYear;
        document.getElementById("manualRefPeriod").value = recYear;

        // 경고 목록 표시
        const warnBox = document.getElementById("warningsContainer");
        const warnList = document.getElementById("warningsList");
        warnList.innerHTML = "";
        if (diag.warnings && diag.warnings.length > 0) {
            diag.warnings.forEach(w => {
                const li = document.createElement("li");
                li.textContent = w;
                warnList.appendChild(li);
            });
            warnBox.classList.remove("hidden");
        } else {
            warnBox.classList.add("hidden");
        }

        // 10행 미리보기 테이블 렌더링
        renderPreviewTable(diag.column_names || [], diag.preview_10_rows || []);
        document.getElementById("colCountSpan").textContent = diag.columns || 0;

        // 섹션 활성화 (진단 결과 + 자연어 쿼리 입력창)
        diagSection.classList.remove("hidden");
        document.getElementById("suggestionsSection").classList.remove("hidden");
        diagSection.scrollIntoView({ behavior: "smooth" });

    } catch (err) {
        console.error("[ERROR]", err.message);
        alert(`진단 오류: ${err.message}`);
    } finally {
        inspectBtn.disabled = false;
        uploadSpinner.classList.add("hidden");
    }
}

/* -------------------------------------------------------------
   4. 분석 제안 API (/suggest)
------------------------------------------------------------- */
async function requestSuggest() {
    const suggestBtn = document.getElementById("suggestBtn");
    const suggestSpinner = document.getElementById("suggestSpinner");
    const suggestionsSection = document.getElementById("suggestionsSection");
    const suggestionsList = document.getElementById("suggestionsList");

    suggestBtn.disabled = true;
    suggestSpinner.classList.remove("hidden");
    console.log("[SUGGEST] 제안 요청 시작");

    try {
        const res = await fetch("/suggest", { method: "POST" });
        const data = await res.json();

        if (!res.ok) {
            throw new Error(data.error || "분석 제안 생성에 실패했습니다.");
        }

        const suggestions = data.suggestions || [];
        console.log(`[SUGGEST] 제안 응답 수신: 제안 개수=${suggestions.length}`);

        // 제안 카드 목록 렌더링
        suggestionsList.innerHTML = "";
        if (suggestions.length === 0) {
            suggestionsList.innerHTML = "<p>제안된 분석 항목이 없습니다.</p>";
        } else {
            suggestions.forEach((item, idx) => {
                const card = document.createElement("div");
                card.className = "suggestion-card";

                const refPeriodText = item.reference_period ? `기준: ${item.reference_period}년` : "전체 시점";

                card.innerHTML = `
                    <div>
                        <div class="sug-header">
                            <span class="sug-tool-name">${idx + 1}. ${item.tool}</span>
                            <span class="sug-ref-period">${refPeriodText}</span>
                        </div>
                        <div class="sug-body">
                            <div class="sug-why">💡 <strong>추천 이유:</strong> ${escapeHtml(item.why)}</div>
                            <div class="sug-caution">⚠️ <strong>해석 주의:</strong> ${escapeHtml(item.caution)}</div>
                        </div>
                    </div>
                    <div class="sug-footer">
                        <button class="btn btn-accent run-sug-btn">이 분석 실행하기 (/run)</button>
                    </div>
                `;

                // 카드 내 실행 버튼 바인딩
                card.querySelector(".run-sug-btn").addEventListener("click", () => {
                    executeTool(item.tool, item.params || {});
                });

                suggestionsList.appendChild(card);
            });
        }

        suggestionsSection.classList.remove("hidden");
        suggestionsSection.scrollIntoView({ behavior: "smooth" });

    } catch (err) {
        console.error("[ERROR]", err.message);
        alert(`제안 오류: ${err.message}`);
    } finally {
        suggestBtn.disabled = false;
        suggestSpinner.classList.add("hidden");
    }
}

/* -------------------------------------------------------------
   5. 도구 실행 API (/run)
------------------------------------------------------------- */
async function executeTool(tool, params) {
    const runSpinner = document.getElementById("runSpinner");
    const resultsSection = document.getElementById("resultsSection");

    runSpinner.classList.remove("hidden");
    const refPeriod = params.reference_period || "미지정";
    console.log(`[RUN] 도구 실행 시작: 도구명=${tool}, 기준시점=${refPeriod}`);

    try {
        const res = await fetch("/run", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ tool: tool, params: params })
        });

        const data = await res.json();
        if (!res.ok) {
            throw new Error(data.error || "도구 실행 실패");
        }

        const result = data.result || {};
        console.log(`[RUN] 도구 실행 결과 수신: ${result.title || tool}`);

        // 결과 헤더 & 배지 업데이트
        document.getElementById("resultTitle").textContent = result.title || tool;
        document.getElementById("resultSummary").textContent = result.summary || "";
        document.getElementById("resPeriod").textContent = result.reference_period || "-";
        document.getElementById("resUsedRows").textContent = (result.used_rows || 0).toLocaleString();
        document.getElementById("resExcludedRows").textContent = (result.excluded_rows || 0).toLocaleString();
        document.getElementById("resExclusionReason").textContent = `제외 사유: ${result.exclusion_reason || "없음"}`;
        document.getElementById("resCautionText").textContent = result.caution || "특이사항 없음";

        // 결과 표 렌더링
        renderResultTable(result.table);

        // Chart.js 차트 렌더링
        renderChart(result.chart_data, result.title);

        // 결과 영역 및 Q&A 영역 표시 및 이동
        resultsSection.classList.remove("hidden");
        document.getElementById("qaSection").classList.remove("hidden");
        
        // 도구별 맞춤 추천 질문 칩 동적 생성
        renderSuggestedQuestions(tool, result);

        resultsSection.scrollIntoView({ behavior: "smooth" });

    } catch (err) {
        console.error("[ERROR]", err.message);
        alert(`실행 오류: ${err.message}`);
    } finally {
        runSpinner.classList.add("hidden");
    }
}

/* -------------------------------------------------------------
   5-1. 자연어 분석 요청 API (/query)
------------------------------------------------------------- */
async function requestNaturalQuery(promptText) {
    const nlBtn = document.getElementById("nlQueryBtn");
    const nlSpinner = document.getElementById("nlSpinner");
    const resultsSection = document.getElementById("resultsSection");

    nlBtn.disabled = true;
    nlSpinner.classList.remove("hidden");
    console.log(`[QUERY] 자연어 분석 요청 시작: '${promptText}'`);

    try {
        const res = await fetch("/query", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ prompt: promptText })
        });

        const data = await res.json();
        if (!res.ok) {
            throw new Error(data.error || "자연어 분석 요청 실패");
        }

        const result = data.result || {};
        console.log(`[QUERY] 자연어 분석 매핑 성공: 도구=${data.matched_tool}, 이유=${data.reason}`);

        // 결과 헤더 & 배지 업데이트
        document.getElementById("resultTitle").textContent = `🎨 [자연어 생성] ${result.title || data.matched_tool}`;
        document.getElementById("resultSummary").textContent = `요청: "${promptText}" → ${result.summary || ""}`;
        document.getElementById("resPeriod").textContent = result.reference_period || "-";
        document.getElementById("resUsedRows").textContent = (result.used_rows || 0).toLocaleString();
        document.getElementById("resExcludedRows").textContent = (result.excluded_rows || 0).toLocaleString();
        document.getElementById("resExclusionReason").textContent = `제외 사유: ${result.exclusion_reason || "없음"}`;
        document.getElementById("resCautionText").textContent = result.caution || "특이사항 없음";

        // 결과 표 렌더링
        renderResultTable(result.table);

        // Chart.js 차트 렌더링
        renderChart(result.chart_data, result.title);

        // 결과 영역 및 Q&A 영역 표시 및 이동
        resultsSection.classList.remove("hidden");
        document.getElementById("qaSection").classList.remove("hidden");
        
        // 추천 질문 칩 동적 생성
        renderSuggestedQuestions(data.matched_tool, result);

        resultsSection.scrollIntoView({ behavior: "smooth" });

    } catch (err) {
        console.error("[ERROR]", err.message);
        alert(`자연어 분석 오류: ${err.message}`);
    } finally {
        nlBtn.disabled = false;
        nlSpinner.classList.add("hidden");
    }
}

/* -------------------------------------------------------------
   6. Chart.js 렌더링 제어
------------------------------------------------------------- */
function renderChart(chartData, title) {
    const chartContainer = document.getElementById("chartContainer");
    const canvas = document.getElementById("insightChart");

    if (currentChartInstance) {
        currentChartInstance.destroy();
        currentChartInstance = null;
    }

    if (!chartData || !chartData.datasets || chartData.datasets.length === 0) {
        chartContainer.classList.add("hidden");
        return;
    }

    chartContainer.classList.remove("hidden");
    const ctx = canvas.getContext("2d");
    const chartType = chartData.type || "bar";

    const config = {
        type: chartType,
        data: {
            labels: chartData.labels || [],
            datasets: chartData.datasets.map(ds => {
                const isBar = chartType === "bar";
                const bgColors = isBar ? (chartData.labels || []).map(lbl => {
                    const lStr = String(lbl);
                    if (lStr.includes("★") || lStr.toLowerCase().includes("korea") || lStr.includes("한국") || lStr.includes("비교")) {
                        return "rgba(239, 68, 68, 0.85)"; // 비교 대상은 눈에 띄는 주황-빨강 강조
                    }
                    return "rgba(30, 58, 138, 0.7)";
                }) : "rgba(13, 148, 136, 0.1)";

                const borderColors = isBar ? (chartData.labels || []).map(lbl => {
                    const lStr = String(lbl);
                    if (lStr.includes("★") || lStr.toLowerCase().includes("korea") || lStr.includes("한국") || lStr.includes("비교")) {
                        return "#b91c1c";
                    }
                    return "#1e3a8a";
                }) : "#0d9488";

                return {
                    label: ds.label || "값",
                    data: ds.data || [],
                    backgroundColor: bgColors,
                    borderColor: borderColors,
                    borderWidth: 2,
                    tension: 0.25,
                    fill: chartType === "line"
                };
            })
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            indexAxis: chartData.indexAxis || "x",
            plugins: {
                title: {
                    display: true,
                    text: title || "분석 시각화",
                    font: { size: 14, weight: "bold" }
                },
                legend: {
                    display: chartData.datasets.length > 1
                }
            },
            scales: {
                y: {
                    beginAtZero: true
                }
            }
        }
    };

    currentChartInstance = new Chart(ctx, config);
    console.log(`[CHART] 차트 렌더 완료: 차트 종류=${chartType}`);
}

/* -------------------------------------------------------------
   7. AI 해석 요청 API (/explain)
------------------------------------------------------------- */
async function requestExplain(mode) {
    const explainBtn = document.getElementById("explainBtn");
    const explainSpinner = document.getElementById("explainSpinner");
    const explanationSection = document.getElementById("explanationSection");
    const explanationContent = document.getElementById("explanationContent");
    const explainModeBadge = document.getElementById("explainModeBadge");

    explainBtn.disabled = true;
    explainSpinner.classList.remove("hidden");
    console.log(`[EXPLAIN] 해석 요청 시작: 모드=${mode}`);

    try {
        const res = await fetch("/explain", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ mode: mode })
        });

        const data = await res.json();
        if (!res.ok) {
            throw new Error(data.error || "해석 생성에 실패했습니다.");
        }

        console.log(`[EXPLAIN] 해석 응답 수신`);

        // 배지 갱신
        if (mode === "B") {
            explainModeBadge.className = "badge badge-accent";
            explainModeBadge.textContent = "모드 B (Pandas 계산값 기반 정밀 보고서)";
        } else {
            explainModeBadge.className = "badge badge-info";
            explainModeBadge.textContent = "모드 A (계산값 없이 추정한 비교 보고서)";
        }

        // Marked.js를 사용하여 마크다운 HTML 렌더링
        if (window.marked) {
            explanationContent.innerHTML = marked.parse(data.explanation || "");
        } else {
            explanationContent.innerHTML = `<pre>${escapeHtml(data.explanation || "")}</pre>`;
        }

        explanationSection.classList.remove("hidden");
        document.getElementById("qaSection").classList.remove("hidden");
        explanationSection.scrollIntoView({ behavior: "smooth" });

    } catch (err) {
        console.error("[ERROR]", err.message);
        alert(`해석 오류: ${err.message}`);
    } finally {
        explainBtn.disabled = false;
        explainSpinner.classList.add("hidden");
    }
}

/* -------------------------------------------------------------
   8. 후속 질문 API (/ask)
------------------------------------------------------------- */
async function requestAsk(questionText) {
    const qaSendBtn = document.getElementById("qaSendBtn");
    const qaSpinner = document.getElementById("qaSpinner");
    const chatHistory = document.getElementById("chatHistory");

    qaSendBtn.disabled = true;
    qaSpinner.classList.remove("hidden");
    console.log(`[ASK] 후속 질문 요청 시작: 질문=${questionText}`);

    // 사용자 질문 말풍선 즉시 추가
    const userBubble = document.createElement("div");
    userBubble.className = "chat-bubble chat-bubble-user";
    userBubble.textContent = questionText;
    chatHistory.appendChild(userBubble);
    chatHistory.scrollTop = chatHistory.scrollHeight;

    try {
        const res = await fetch("/ask", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ question: questionText })
        });

        const data = await res.json();
        if (!res.ok) {
            throw new Error(data.error || "답변 생성 실패");
        }

        console.log("[ASK] 후속 질문 응답 수신");

        // AI 답변 말풍선 추가 (마크다운 지원)
        const aiBubble = document.createElement("div");
        aiBubble.className = "chat-bubble chat-bubble-ai";
        if (window.marked) {
            aiBubble.innerHTML = marked.parse(data.answer || "");
        } else {
            aiBubble.textContent = data.answer || "";
        }
        chatHistory.appendChild(aiBubble);
        chatHistory.scrollTop = chatHistory.scrollHeight;

    } catch (err) {
        console.error("[ERROR]", err.message);
        const errBubble = document.createElement("div");
        errBubble.className = "chat-bubble chat-bubble-ai";
        errBubble.style.color = "#dc2626";
        errBubble.textContent = `⚠️ 오류: ${err.message}`;
        chatHistory.appendChild(errBubble);
    } finally {
        qaSendBtn.disabled = false;
        qaSpinner.classList.add("hidden");
    }
}

/* -------------------------------------------------------------
   9. 도구별 추천 질문 칩 동적 생성
------------------------------------------------------------- */
function renderSuggestedQuestions(tool, result) {
    const container = document.getElementById("suggestedQuestionsList");
    container.innerHTML = "";

    // 도구 유형에 따른 지능형 추천 질문 매핑
    let questions = [];

    switch (tool) {
        case "top_bottom_n":
            questions = [
                "1위와 2위 국가의 수치 차이는 얼마인가요?",
                "하위권 국가들의 수치 수준은 어떻게 되나요?",
                "이 분석에서 집계 행과 결측치는 총 몇 개 제외되었나요?",
                "우리나라(Korea, Rep.)는 몇 위에 위치해 있나요?"
            ];
            break;
        case "change_rate":
            questions = [
                "가장 큰 폭으로 증가한 1위 국가는 어디인가요?",
                "비교 기간 동안 수치가 감소한 국가도 있나요?",
                "변화량(포인트)과 성장률(%)의 차이를 쉽게 설명해 주세요.",
                "이 변화율을 볼 때 주의해야 할 통계적 한계는 무엇인가요?"
            ];
            break;
        case "distribution":
            questions = [
                "가장 많은 국가가 몰려 있는 구간은 어디인가요?",
                "분포가 한쪽으로 치우쳐 있나요, 아니면 고르게 퍼져 있나요?",
                "극단적으로 수치가 낮거나 높은 이상치 구간이 있나요?",
                "전체 평균값과 이 분포의 중심은 일치하나요?"
            ];
            break;
        case "correlation_scatter":
            questions = [
                "이 상관계수(r)가 의미하는 실질적인 관계 강도는 어떤가요?",
                "이 결과를 바탕으로 원인과 결과를 단정할 수 없는 이유는 무엇인가요?",
                "두 변수 중 어느 한쪽이라도 결측치여서 제외된 항목은 몇 개였나요?",
                "산점도에서 대각선 추세와 멀리 떨어진 예외 국가가 있나요?"
            ];
            break;
        case "compare_one_vs_all":
            questions = [
                "선택한 국가는 전체 평균보다 얼마나 높거나 낮은가요?",
                "중앙값과 비교했을 때 상위 몇 % 수준에 해당하나요?",
                "왜 평균뿐만 아니라 중앙값도 함께 비교해야 하나요?",
                "이 국가와 비슷한 수치를 가진 다른 국가들은 어디가 있나요?"
            ];
            break;
        case "trend_line":
            questions = [
                "시간이 흐르면서 국가 간 격차가 벌어지고 있나요, 좁혀지고 있나요?",
                "성장 속도가 가장 가파르게 빨라진 시기는 언제인가요?",
                "중간에 데이터가 누락되거나 선이 끊긴 연도가 있나요?",
                "이 시계열 추세에서 가장 두드러진 특징은 무엇인가요?"
            ];
            break;
        default:
            questions = [
                "이 분석 결과에서 가장 핵심적인 숫자는 무엇인가요?",
                "제외된 데이터가 전체 결론에 어떤 영향을 미칠 수 있나요?",
                "이 데이터로는 확인할 수 없는 한계점은 무엇인가요?",
                "다음에 추가로 검증해보면 좋은 분석 도구는 무엇인가요?"
            ];
            break;
    }

    // 추천 질문 칩 생성 및 클릭 이벤트 바인딩
    questions.forEach(qText => {
        const chip = document.createElement("button");
        chip.type = "button";
        chip.className = "question-chip";
        chip.textContent = `💬 ${qText}`;
        chip.addEventListener("click", () => {
            document.getElementById("qaInput").value = qText;
            requestAsk(qText);
        });
        container.appendChild(chip);
    });
}

/* -------------------------------------------------------------
   8. 유틸리티 함수 (테이블 렌더링 & 서식)
------------------------------------------------------------- */
function renderPreviewTable(columns, rows) {
    const thead = document.getElementById("previewThead");
    const tbody = document.getElementById("previewTbody");
    thead.innerHTML = "";
    tbody.innerHTML = "";

    if (!columns || columns.length === 0) return;

    const trHead = document.createElement("tr");
    columns.forEach(col => {
        const th = document.createElement("th");
        th.textContent = col;
        trHead.appendChild(th);
    });
    thead.appendChild(trHead);

    rows.forEach(row => {
        const tr = document.createElement("tr");
        columns.forEach(col => {
            const td = document.createElement("td");
            td.textContent = (row[col] !== null && row[col] !== undefined) ? row[col] : "-";
            tr.appendChild(td);
        });
        tbody.appendChild(tr);
    });
}

function renderResultTable(tableData) {
    const thead = document.getElementById("resultThead");
    const tbody = document.getElementById("resultTbody");
    thead.innerHTML = "";
    tbody.innerHTML = "";

    if (!tableData || !Array.isArray(tableData) || tableData.length === 0) {
        thead.innerHTML = "<tr><th>결과</th></tr>";
        tbody.innerHTML = "<tr><td>표 형태의 데이터가 없습니다.</td></tr>";
        return;
    }

    const firstRow = tableData[0];
    const keys = Object.keys(firstRow);

    const trHead = document.createElement("tr");
    keys.forEach(k => {
        const th = document.createElement("th");
        th.textContent = k;
        trHead.appendChild(th);
    });
    thead.appendChild(trHead);

    tableData.forEach(row => {
        const tr = document.createElement("tr");
        const rowString = JSON.stringify(row);
        const isHighlighted = rowString.includes("★") || rowString.includes("비교") || rowString.toLowerCase().includes("korea");
        if (isHighlighted) {
            tr.style.backgroundColor = "#fef3c7"; // 은은한 앰버/노란색 하이라이트
            tr.style.fontWeight = "bold";
            tr.style.color = "#92400e";
        }
        keys.forEach(k => {
            const td = document.createElement("td");
            const val = row[k];
            td.textContent = (val !== null && val !== undefined) ? val : "-";
            tr.appendChild(td);
        });
        tbody.appendChild(tr);
    });
}

function formatBytes(bytes) {
    if (bytes === 0) return "0 Bytes";
    const k = 1024;
    const sizes = ["Bytes", "KB", "MB", "GB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + " " + sizes[i];
}

function escapeHtml(str) {
    if (!str) return "";
    return str
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}
