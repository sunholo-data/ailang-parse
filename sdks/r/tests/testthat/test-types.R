block <- function(type, ...) ailangparse:::.block_from_list(list(type = type, ...))

test_that("text block parses", {
  b <- block("text", text = "hello world")
  expect_s3_class(b, "ailang_block_text")
  expect_s3_class(b, "ailang_block")
  expect_equal(b$text, "hello world")
})

test_that("heading block carries level", {
  b <- block("heading", text = "Title", level = 2L)
  expect_s3_class(b, "ailang_block_heading")
  expect_equal(b$level, 2L)
  expect_match(format(b), "H2: Title")
})

test_that("table block parses headers and rows, supports as.data.frame", {
  b <- block(
    "table",
    headers = list("Name", "Score"),
    rows = list(
      list("Alice", "10"),
      list(list(text = "Bob", colSpan = 1L, merged = FALSE), "20")
    )
  )
  expect_s3_class(b, "ailang_block_table")
  expect_length(b$headers, 2L)
  expect_equal(b$headers[[1]]$text, "Name")
  expect_length(b$rows, 2L)
  expect_equal(b$rows[[2]][[1]]$text, "Bob")

  df <- as.data.frame(b)
  expect_s3_class(df, "data.frame")
  expect_equal(names(df), c("Name", "Score"))
  expect_equal(df$Name, c("Alice", "Bob"))
})

test_that("list block parses items and ordered flag", {
  b <- block("list", items = list("a", "b", "c"), ordered = TRUE)
  expect_s3_class(b, "ailang_block_list")
  expect_equal(b$items, c("a", "b", "c"))
  expect_true(b$ordered)
})

test_that("image / audio / video blocks parse media fields", {
  for (kind in c("image", "audio", "video")) {
    b <- block(kind, mime = "image/png", dataLength = 1234L,
               description = "alt text", transcription = "")
    expect_s3_class(b, paste0("ailang_block_", kind))
    expect_equal(b$mime, "image/png")
    expect_equal(b$data_length, 1234L)
    expect_equal(b$description, "alt text")
  }
})

test_that("section block recursively parses children", {
  b <- block(
    "section",
    kind = "chapter",
    blocks = list(
      list(type = "heading", text = "Intro", level = 1L),
      list(type = "text",    text = "body")
    )
  )
  expect_s3_class(b, "ailang_block_section")
  expect_length(b$children, 2L)
  expect_s3_class(b$children[[1]], "ailang_block_heading")
  expect_equal(b$children[[2]]$text, "body")
})

test_that("change block carries change_type / author / date", {
  b <- block("change", changeType = "insertion", author = "Mark",
             date = "2026-04-07", text = "added")
  expect_s3_class(b, "ailang_block_change")
  expect_equal(b$change_type, "insertion")
  expect_equal(b$author, "Mark")
  expect_match(format(b), "insertion by Mark: added")
})

test_that("ParseResult parses blocks + metadata + summary", {
  raw <- list(
    status   = "success",
    filename = "x.docx",
    format   = "zip-office",
    blocks   = list(list(type = "text", text = "hi")),
    metadata = list(title = "T", author = "A", pageCount = 3L),
    summary  = list(totalBlocks = 1L, headings = 0L, tables = 0L,
                    images = 0L, changes = 0L)
  )
  res <- ailangparse:::.parse_result_from_list(raw)
  expect_s3_class(res, "ailang_parse_result")
  expect_equal(res$status, "success")
  expect_length(res$blocks, 1L)
  expect_equal(res$metadata$title, "T")
  expect_equal(res$metadata$page_count, 3L)
  expect_equal(res$summary$total_blocks, 1L)
})

test_that("blocks decode inline runs and itemRuns", {
  b <- ailangparse:::.block_from_list(list(
    type = "text", text = "plain bold x2",
    runs = list(
      list(text = "plain "),
      list(text = "bold", bold = TRUE),
      list(text = "2", vertAlign = "superscript")
    )
  ))
  expect_length(b$runs, 3L)
  expect_equal(vapply(b$runs, function(r) r$text, character(1)),
               c("plain ", "bold", "2"))
  expect_true(b$runs[[2]]$bold)
  expect_false(b$runs[[1]]$bold)
  expect_equal(b$runs[[3]]$vert_align, "superscript")

  # item_runs is parallel to items; an unformatted item has no runs
  l <- ailangparse:::.block_from_list(list(
    type = "list", items = list("one", "two"),
    itemRuns = list(list(list(text = "one", italic = TRUE)), list())
  ))
  expect_length(l$item_runs, length(l$items))
  expect_true(l$item_runs[[1]][[1]]$italic)
  expect_length(l$item_runs[[2]], 0L)
})

test_that("blocks with no formatting keep the pre-InlineRun shape", {
  plain <- ailangparse:::.block_from_list(list(type = "text", text = "nothing here"))
  expect_length(plain$runs, 0L)
  expect_length(plain$item_runs, 0L)
})
