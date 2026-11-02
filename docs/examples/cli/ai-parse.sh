# Generate a DOCX report from a prompt
ailang run --entry main --caps IO,FS,Env,AI --ai gemini-3.8-flash \
  docparse/main.ail --generate report.docx --prompt "Q1 sales report with revenue table"