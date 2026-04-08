#' Unstructured.io API compatibility layer
#'
#' Drop-in replacement for the \code{UnstructuredClient} class shipped by
#' \pkg{unstructured-client} (Python) and similar wrappers. Posts to
#' \code{/general/v0/general} on the configured server, returning a list of
#' \code{Element} records with the same field names as the Unstructured API.
#'
#' Migration from a hypothetical \code{unstructured} R wrapper:
#' \preformatted{
#' uc <- ailangparse::UnstructuredClient$new(
#'   server_url = "https://docparse.ailang.sunholo.com"
#' )
#' elements <- uc$partition("report.docx", strategy = "auto")
#' }
#'
#' @examples
#' \dontrun{
#' uc <- UnstructuredClient$new()
#' uc$partition("report.docx", strategy = "auto")
#' }
#' @export
UnstructuredClient <- R6::R6Class(
  "UnstructuredClient",
  public = list(
    #' @field server_url Base URL of the Unstructured-compatible endpoint.
    server_url = NULL,
    #' @field api_key Active API key, or \code{""}.
    api_key = NULL,
    #' @field timeout Per-request timeout in seconds.
    timeout = NULL,

    #' @description Construct a new client.
    #' @param server_url Base URL of the Unstructured-compatible endpoint.
    #' @param api_key Optional API key. If empty, the env var
    #'   \code{DOCPARSE_API_KEY} and saved credentials are consulted.
    #' @param timeout Per-request timeout in seconds.
    initialize = function(server_url = default_base_url(),
                          api_key = NULL,
                          timeout = 60) {
      self$server_url <- sub("/$", "", server_url)
      self$timeout    <- timeout
      key <- if (is.null(api_key)) "" else api_key
      if (!nzchar(key)) {
        key <- Sys.getenv("DOCPARSE_API_KEY", unset = "")
      }
      if (!nzchar(key)) {
        saved <- load_saved_key(self$server_url)
        if (!is.null(saved)) key <- saved$api_key
      }
      self$api_key <- key
      invisible(self)
    },

    #' @description Partition a document into Unstructured-style elements.
    #' @param file Local file path (uploaded multipart) or sample ID /
    #'   server-side filepath (sent as JSON).
    #' @param strategy Partitioning strategy passed to the API
    #'   (default \code{"auto"}).
    #' @return A list of element records (each a list with \code{type},
    #'   \code{element_id}, \code{text}, \code{metadata}).
    partition = function(file, strategy = "auto") {
      url_path <- "/general/v0/general"
      req <- httr2::request(paste0(self$server_url, url_path))
      req <- httr2::req_timeout(req, self$timeout)
      req <- httr2::req_user_agent(req, "ailangparse-r/0.4.1")
      req <- httr2::req_error(req, is_error = function(resp) FALSE)
      if (nzchar(self$api_key)) {
        req <- httr2::req_headers(req, `unstructured-api-key` = self$api_key)
      }

      if (file.exists(file)) {
        req <- httr2::req_body_multipart(
          req,
          files    = curl::form_file(file, name = basename(file)),
          strategy = strategy
        )
      } else {
        req <- httr2::req_body_json(
          req,
          list(
            filepath = jsonlite::unbox(file),
            strategy = jsonlite::unbox(strategy)
          )
        )
      }

      body_text <- .perform(req)
      outer <- tryCatch(
        jsonlite::fromJSON(body_text, simplifyVector = FALSE),
        error = function(e) {
          stop(.docparse_error(sprintf("Invalid JSON response: %s",
                                       conditionMessage(e))))
        }
      )
      if (!is.null(outer$error) && length(outer$error) > 0L) {
        stop(.docparse_error(as.character(outer$error)))
      }
      result_str <- if (is.null(outer$result)) "[]" else outer$result
      elements_raw <- tryCatch(
        jsonlite::fromJSON(result_str, simplifyVector = FALSE),
        error = function(e) list()
      )
      if (is.list(elements_raw) && !is.null(elements_raw$error)) {
        err <- elements_raw$error
        msg <- if (is.list(err) && !is.null(err$message)) err$message
               else as.character(err)
        stop(.docparse_error(msg))
      }
      if (!is.list(elements_raw)) return(list())
      lapply(elements_raw, .element_from_list)
    }
  )
)
