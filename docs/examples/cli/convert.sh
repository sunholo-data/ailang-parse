# DOCX to HTML
./bin/docparse input.docx --convert output.html

# CSV to DOCX report
./bin/docparse data.csv --convert report.docx

# Markdown to PowerPoint slides
./bin/docparse notes.md --convert slides.pptx

# Any format to Quarto Markdown (for Quarto rendering)
./bin/docparse report.docx --convert report.qmd