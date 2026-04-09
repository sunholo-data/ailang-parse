#' Run the AILANG Parse MCP stdio bridge
#'
#' Bridges JSON-RPC over stdio to the hosted AILANG Parse MCP HTTP endpoint.
#' Suitable as a Claude Desktop / Cursor / VS Code MCP server. Mirrors the
#' Python, JavaScript and Go MCP bridges shipped with the same SDK family.
#'
#' Behaviour:
#' \itemize{
#'   \item Reads newline-delimited JSON-RPC messages from \code{stdin}.
#'   \item Captures and replays the \code{Mcp-Session-Id} header.
#'   \item Auto-loads any saved API key via \code{\link{resolve_api_key}}
#'         and injects it into empty \code{tools/call} arguments and an
#'         \code{Authorization: Bearer ...} header.
#'   \item Handles both direct JSON and SSE responses.
#'   \item Logs to \code{stderr} with the prefix \code{[ailang-parse-mcp]}.
#' }
#'
#' Set \code{AILANG_PARSE_MCP_URL} to override the endpoint.
#'
#' Claude Desktop config (\code{claude_desktop_config.json}):
#' \preformatted{
#' {
#'   "mcpServers": {
#'     "ailang-parse": {
#'       "command": "Rscript",
#'       "args": ["-e", "ailangparse::mcp()"]
#'     }
#'   }
#' }
#' }
#'
#' @return Invisible \code{NULL}. The function returns when stdin closes.
#' @examples
#' \dontrun{
#' mcp()
#' }
#' @export
mcp <- function() {
  endpoint <- Sys.getenv("AILANG_PARSE_MCP_URL",
                         unset = "https://docparse.ailang.sunholo.com/mcp/")
  state <- new.env(parent = emptyenv())
  state$session_id <- NULL
  state$api_key    <- resolve_api_key()

  .mcp_log(paste0("Connecting to ", endpoint))
  if (!is.null(state$api_key) && nzchar(state$api_key)) {
    tail4 <- substr(state$api_key, max(1L, nchar(state$api_key) - 3L),
                    nchar(state$api_key))
    .mcp_log(paste0("Using saved API key (\u2026", tail4, ")"))
  } else {
    .mcp_log("No API key found - agent will need to call mcpAuth on first parse")
  }

  con <- stdin()
  repeat {
    line <- readLines(con, n = 1L, warn = FALSE)
    if (length(line) == 0L) break
    line <- trimws(line)
    if (!nzchar(line)) next

    msg <- tryCatch(
      jsonlite::fromJSON(line, simplifyVector = FALSE),
      error = function(e) NULL
    )
    if (is.null(msg)) next

    tryCatch(
      .mcp_forward(msg, endpoint, state),
      error = function(e) {
        method <- if (is.list(msg) && !is.null(msg$method)) msg$method else "unknown"
        if (is.list(msg) && !is.null(msg$id)) {
          .mcp_write(list(
            jsonrpc = jsonlite::unbox("2.0"),
            id      = msg$id,
            error   = list(
              code    = jsonlite::unbox(-32000L),
              message = jsonlite::unbox(paste0("MCP bridge error: ",
                                               conditionMessage(e)))
            )
          ))
        }
        .mcp_log(paste0("Error forwarding ", method, ": ", conditionMessage(e)))
      }
    )
  }
  invisible(NULL)
}

.mcp_log <- function(msg) {
  cat(paste0("[ailang-parse-mcp] ", msg, "\n"), file = stderr())
  flush(stderr())
}

.mcp_write <- function(obj) {
  cat(jsonlite::toJSON(obj, auto_unbox = FALSE, null = "null"), "\n",
      sep = "", file = stdout())
  flush(stdout())
}

.mcp_inject_api_key <- function(msg, api_key) {
  if (is.null(api_key) || !nzchar(api_key)) return(msg)
  if (!identical(.s(msg$method), "tools/call")) return(msg)
  args <- msg$params$arguments
  if (!is.list(args)) return(msg)
  if ("apiKey" %in% names(args) && (is.null(args$apiKey) || !nzchar(args$apiKey))) {
    msg$params$arguments$apiKey <- jsonlite::unbox(api_key)
  }
  msg
}

.mcp_forward <- function(msg, endpoint, state) {
  msg <- .mcp_inject_api_key(msg, state$api_key)

  req <- httr2::request(endpoint)
  req <- httr2::req_method(req, "POST")
  req <- httr2::req_timeout(req, 300)
  req <- httr2::req_user_agent(req, "ailangparse-r/0.5.0")
  req <- httr2::req_error(req, is_error = function(resp) FALSE)
  req <- httr2::req_headers(
    req,
    `Content-Type` = "application/json",
    Accept         = "application/json, text/event-stream"
  )
  if (!is.null(state$session_id)) {
    req <- httr2::req_headers(req, `Mcp-Session-Id` = state$session_id)
  }
  if (!is.null(state$api_key) && nzchar(state$api_key)) {
    req <- httr2::req_headers(req, Authorization = paste("Bearer", state$api_key))
  }
  req <- httr2::req_body_raw(req, jsonlite::toJSON(msg, auto_unbox = FALSE),
                             type = "application/json")

  resp <- httr2::req_perform(req)
  status <- httr2::resp_status(resp)
  sid <- tryCatch(httr2::resp_header(resp, "Mcp-Session-Id"),
                  error = function(e) NULL)
  if (!is.null(sid) && nzchar(sid)) state$session_id <- sid

  if (status %in% c(202L, 204L)) return(invisible(NULL))

  if (status >= 400L) {
    body <- tryCatch(httr2::resp_body_string(resp), error = function(e) "")
    stop(sprintf("HTTP %d: %s", status, substr(body, 1L, 200L)))
  }

  ctype <- tryCatch(httr2::resp_header(resp, "Content-Type"),
                    error = function(e) "")
  body <- httr2::resp_body_string(resp)

  if (grepl("text/event-stream", ctype %||% "", fixed = TRUE)) {
    for (ln in strsplit(body, "\n", fixed = TRUE)[[1L]]) {
      if (startsWith(ln, "data: ")) {
        data <- trimws(substring(ln, 7L))
        if (nzchar(data)) {
          cat(data, "\n", sep = "", file = stdout())
        }
      }
    }
    flush(stdout())
  } else {
    text <- trimws(body)
    if (nzchar(text)) {
      cat(text, "\n", sep = "", file = stdout())
      flush(stdout())
    }
  }
  invisible(NULL)
}

`%||%` <- function(a, b) if (is.null(a)) b else a
