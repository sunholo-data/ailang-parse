library(ailangparse)

client <- DocParse$new(api_key = "dp_your_key_here")

result <- client$parse("report.docx")
for (block in result$blocks) {
  if (block$type == "heading") {
    cat("H", block$level, ": ", block$text, "\n", sep = "")
  } else if (block$type == "table") {
    cat("Table:", length(block$rows), "rows\n")
  } else if (block$type == "change") {
    cat(block$change_type, "by", block$author, "\n")
  }
}

# Tables become data frames:
tables <- Filter(function(b) inherits(b, "ailang_block_table"), result$blocks)
if (length(tables) > 0) print(as.data.frame(tables[[1]]))

# Unstructured migration — one import change:
uc <- UnstructuredClient$new(server_url = "https://docparse.ailang.sunholo.com")
elements <- uc$partition("report.docx")
