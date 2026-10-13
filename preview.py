"""Export a self-contained, clearly limited static review demo."""
import json
from .copilot import ask


def export_preview(root, output):
    report = json.loads((root / "artifacts/dashboard.json").read_text())
    cases = json.loads((root / "docs/eval_cases.json").read_text())
    answers = {case["question"]: ask(report, case["question"]) for case in cases}
    prepared = ["What changed in portfolio delinquency this month?", "How are roll rates computed?",
                "How was the model evaluated?", "What caused the delinquency increase?"]
    for question in prepared:
        answers[question] = ask(report, question)
    shim = """
const SAMPLE_REPORT = __REPORT__;
const PREPARED_ANSWERS = __ANSWERS__;
window.fetch=async (url,options)=>{
  if(url==='/api/dashboard') return {ok:true,json:async()=>SAMPLE_REPORT};
  if(url==='/api/config') return {ok:true,json:async()=>({openai_available:false})};
  const q=JSON.parse(options.body).question;
  const answer=PREPARED_ANSWERS[q]||{status:'abstained',mode:'offline_evidence_template',
    summary:'This self-contained preview has prepared sample answers only. Use the sample questions here, or run the Python project to ask a new question.',
    evidence:[],evidence_ids:[],limitations:['Static preview, synthetic data. No model training or API request runs in this file.'],elapsed_ms:0};
  return {ok:true,json:async()=>answer};
};
""".replace("__REPORT__", json.dumps(report).replace("</", "<\\/"))
    shim = shim.replace("__ANSWERS__", json.dumps(answers).replace("</", "<\\/"))
    html = (root / "web/index.html").read_text()
    html = html.replace('<link rel="stylesheet" href="/style.css">', "<style>" + (root / "web/style.css").read_text() + "</style>")
    html = html.replace('<script src="/app.js"></script>', "<script>" + shim + "\n" + (root / "web/app.js").read_text() + "</script>")
    html = html.replace('href="/"', 'href="#"')
    html = html.replace("LOCAL DEMO", "STATIC PREVIEW")
    html = html.replace("The copilot retrieves computed facts and metric definitions. It declines questions outside its evidence.",
        "This preview has prepared sample answers. Run the Python project for new questions within the evidence scope.")
    html = html.replace("Personal portfolio prototype · Synthetic data · Reproducible build",
        "Static preview · Synthetic data · Sample answers only")
    output.write_text(html, encoding="utf-8")
    return output
