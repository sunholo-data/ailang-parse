@echo off
setlocal enabledelayedexpansion

:: AILANG Parse CLI for Windows — Universal Document Parsing
:: Wrapper around ailang that handles caps, AI model, and flags automatically.

set "SCRIPT_DIR=%~dp0"
set "PROJECT_DIR=%SCRIPT_DIR%.."
set "MAIN_AIL=docparse\main.ail"
set "DEFAULT_AI_MODEL=gemini-3-flash-preview"

:: Supported extensions for folder scanning
set "SUPPORTED_EXTS=docx pptx xlsx odt odp ods html htm md csv epub eml mbox pdf png jpg jpeg gif bmp webp tiff tif mp3 wav ogg flac mp4 mov avi mkv"

:: --- Parse arguments ---

set "DESCRIBE="
set "SUMMARIZE="
set "AI_MODEL=%DEFAULT_AI_MODEL%"
set "VERIFY="
set "BUDGET="
set "OUTPUT_DIR="
set "FILE_COUNT=0"

:parse_args
if "%~1"=="" goto args_done

if /i "%~1"=="-h"       goto show_help
if /i "%~1"=="--help"   goto show_help
if /i "%~1"=="--check"  goto do_check
if /i "%~1"=="--test"   goto do_test
if /i "%~1"=="--prove"  goto do_prove
if /i "%~1"=="--eval"   goto do_eval

if /i "%~1"=="--describe" (
    set "DESCRIBE=1"
    shift
    goto parse_args
)
if /i "%~1"=="--summarize" (
    set "SUMMARIZE=1"
    shift
    goto parse_args
)
if /i "%~1"=="--ai" (
    set "AI_MODEL=%~2"
    shift & shift
    goto parse_args
)
if /i "%~1"=="--verify" (
    set "VERIFY=1"
    shift
    goto parse_args
)
if /i "%~1"=="--budget-report" (
    set "BUDGET=1"
    shift
    goto parse_args
)
if /i "%~1"=="--output-dir" (
    set "OUTPUT_DIR=%~f2"
    shift & shift
    goto parse_args
)

:: Check if argument is a directory
if exist "%~f1\" (
    call :expand_folder "%~f1"
    shift
    goto parse_args
)

:: Check if argument is a file
if exist "%~f1" (
    set /a FILE_COUNT+=1
    set "FILE_!FILE_COUNT!=%~f1"
    shift
    goto parse_args
)

:: Unknown flag or non-existent file
echo Error: File or folder not found: %~1
exit /b 1

:args_done

if %FILE_COUNT% equ 0 goto show_help

:: --- Detect if AI is needed ---

set "NEEDS_AI="
for /l %%i in (1,1,%FILE_COUNT%) do (
    set "F=!FILE_%%i!"
    for %%e in (pdf png jpg jpeg gif bmp webp tiff tif mp3 wav ogg flac mp4 mov avi mkv) do (
        if /i "!F:~-4!"==".%%e" set "NEEDS_AI=1"
        if /i "!F:~-5!"==".%%e" set "NEEDS_AI=1"
    )
)

set "USE_AI="
if defined NEEDS_AI set "USE_AI=1"
if defined DESCRIBE set "USE_AI=1"
if defined SUMMARIZE set "USE_AI=1"

:: --- Build ailang command ---

set "CAPS=IO,FS,Env"
if defined USE_AI set "CAPS=IO,FS,Env,AI"

set "USE_BATCH="
if %FILE_COUNT% gtr 1 set "USE_BATCH=1"

set "CMD=ailang run"
if defined USE_BATCH set "CMD=!CMD! --batch"
set "CMD=!CMD! --entry main --caps %CAPS% --max-recursion-depth 50000"

if defined USE_AI set "CMD=!CMD! --ai %AI_MODEL%"
if defined VERIFY set "CMD=!CMD! --verify-contracts"
if defined BUDGET set "CMD=!CMD! --budget-report"

set "CMD=!CMD! %MAIN_AIL%"

:: AILANG args (passed after file)
set "AILANG_ARGS="
if defined DESCRIBE set "AILANG_ARGS=!AILANG_ARGS! describe"
if defined SUMMARIZE set "AILANG_ARGS=!AILANG_ARGS! summarize"

:: --- Run ---

pushd "%PROJECT_DIR%"

set "OUTPUT_BASE=docparse\data"

if defined USE_BATCH (
    echo Batch mode: parsing %FILE_COUNT% files ^(compile once^)...
    echo.

    set "FULL_CMD=!CMD!"
    for /l %%i in (1,1,%FILE_COUNT%) do (
        set "FULL_CMD=!FULL_CMD! !FILE_%%i! %AILANG_ARGS%"
    )

    if defined USE_AI (
        !FULL_CMD!
    ) else (
        !FULL_CMD!
    )

    echo.
    echo Batch complete: %FILE_COUNT% files

    if defined OUTPUT_DIR (
        if not exist "%OUTPUT_DIR%" mkdir "%OUTPUT_DIR%"
        for /l %%i in (1,1,%FILE_COUNT%) do (
            for %%f in ("!FILE_%%i!") do set "BASENAME=%%~nxf"
            for %%e in (.json .md _summary.txt) do (
                if exist "%OUTPUT_BASE%\!BASENAME!%%e" copy /y "%OUTPUT_BASE%\!BASENAME!%%e" "%OUTPUT_DIR%\" >nul
            )
        )
        echo Output copied to %OUTPUT_DIR%\
    )
) else (
    :: Single file
    set "FILE=!FILE_1!"
    set "FULL_CMD=!CMD! !FILE! %AILANG_ARGS%"

    if defined USE_AI (
        !FULL_CMD!
    ) else (
        !FULL_CMD!
    )

    if defined OUTPUT_DIR (
        for %%f in ("!FILE!") do set "BASENAME=%%~nxf"
        if not exist "%OUTPUT_DIR%" mkdir "%OUTPUT_DIR%"
        for %%e in (.json .md _summary.txt) do (
            if exist "%OUTPUT_BASE%\!BASENAME!%%e" copy /y "%OUTPUT_BASE%\!BASENAME!%%e" "%OUTPUT_DIR%\" >nul
        )
        echo.
        echo Output copied to %OUTPUT_DIR%\
    )
)

popd
exit /b 0

:: --- Subroutines ---

:show_help
echo AILANG Parse -- Universal Document Parsing
echo.
echo Usage: docparse ^<file^|folder^> [file2 ...] [options]
echo        docparse --check
echo        docparse --test
echo.
echo Examples:
echo   docparse report.docx                  Parse Office document
echo   docparse *.eml                        Batch parse (compile once)
echo   docparse C:\inbox\                    Parse all files in folder
echo   docparse slides.pptx --describe       With AI image descriptions
echo   docparse report.docx --summarize      With AI summary
echo   docparse scan.pdf                     PDF (auto-enables AI)
echo.
echo Options:
echo   --describe        Enable AI image descriptions
echo   --summarize       Enable AI document summary
echo   --ai MODEL        AI model (default: gemini-3-flash-preview)
echo   --verify          Enable runtime contract verification
echo   --budget-report   Show capability budget usage after run
echo   --output-dir DIR  Copy output files to DIR after parsing
echo   --check           Type-check all modules (no file needed)
echo   --test            Run all inline tests (no file needed)
echo   --prove           Static Z3 contract verification (no file needed)
echo   --eval            Run AILANG eval on all golden files (no file needed)
echo   -h, --help        Show this help
echo.
echo Supported formats:
echo   Office:  .docx .pptx .xlsx  (deterministic XML parsing)
echo   AI:      .pdf .png .jpg .gif .bmp .webp .tiff .mp3 .wav .mp4  (multimodal AI)
echo.
echo Output:
echo   docparse\data\output.json     Structured JSON with typed blocks
echo   docparse\data\output.md       LLM-ready markdown
exit /b 0

:do_check
pushd "%PROJECT_DIR%"
echo Type-checking all AILANG Parse modules...
for %%m in (
    docparse\types\document.ail
    docparse\services\format_router.ail
    docparse\services\zip_extract.ail
    docparse\services\docx_parser.ail
    docparse\services\pptx_parser.ail
    docparse\services\xlsx_parser.ail
    docparse\services\direct_ai_parser.ail
    docparse\services\layout_ai.ail
    docparse\services\output_formatter.ail
    docparse\services\csv_parser.ail
    docparse\services\markdown_parser.ail
    docparse\services\html_parser.ail
    docparse\services\epub_parser.ail
    docparse\services\odt_parser.ail
    docparse\services\odp_parser.ail
    docparse\services\ods_parser.ail
    docparse\services\eval.ail
    docparse\services\unstructured_compat.ail
    docparse\services\eml_parser.ail
    docparse\services\xml_helpers.ail
    docparse\services\a2ui_formatter.ail
    docparse\services\samples.ail
    docparse\services\tools.ail
    docparse\services\docparse_browser.ail
    docparse\services\html_generator.ail
    docparse\services\docx_generator.ail
    docparse\services\pptx_generator.ail
    docparse\services\xlsx_generator.ail
    docparse\services\odt_generator.ail
    docparse\services\odp_generator.ail
    docparse\services\ods_generator.ail
    docparse\services\qmd_generator.ail
    docparse\services\ai_generator.ail
    docparse\main.ail
) do (
    echo   %%~nxm ...
    ailang check "%%m" >nul 2>&1 && echo     OK || echo     FAIL
)
popd
exit /b 0

:do_test
pushd "%PROJECT_DIR%"
echo Running inline tests...
for %%m in (
    docparse\services\format_router.ail
    docparse\services\zip_extract.ail
    docparse\services\docx_parser.ail
    docparse\services\odt_parser.ail
    docparse\services\odp_parser.ail
) do (
    echo.
    echo --- %%~nxm ---
    ailang test "%%m"
)
popd
exit /b 0

:do_prove
pushd "%PROJECT_DIR%"
echo Static contract verification (Z3)...
echo.
for %%m in (
    docparse\types\document.ail
    docparse\services\format_router.ail
    docparse\services\zip_extract.ail
    docparse\services\docx_parser.ail
    docparse\services\pptx_parser.ail
    docparse\services\xlsx_parser.ail
    docparse\services\csv_parser.ail
    docparse\services\markdown_parser.ail
    docparse\services\html_parser.ail
    docparse\services\epub_parser.ail
    docparse\services\odt_parser.ail
    docparse\services\odp_parser.ail
    docparse\services\ods_parser.ail
    docparse\services\eml_parser.ail
    docparse\main.ail
) do (
    ailang verify "%%m"
    echo.
)
popd
exit /b 0

:do_eval
pushd "%PROJECT_DIR%"
echo Running AILANG eval on all golden files...
set "GOLDEN_DIR=benchmarks\office\golden"
set "TEST_DIR=data\test_files"
set "EVAL_PASS=0"
set "EVAL_FAIL=0"
set "EVAL_TOTAL=0"

:: Create temp dir
set "EVAL_TMPDIR=%TEMP%\docparse_eval_%RANDOM%"
mkdir "%EVAL_TMPDIR%"

:: Collect and batch-parse files
set "BATCH_FILES="
for %%g in ("%GOLDEN_DIR%\*.json") do (
    set "FNAME=%%~ng"
    if exist "%TEST_DIR%\!FNAME!" (
        set /a EVAL_TOTAL+=1
        set "BATCH_FILES=!BATCH_FILES! %TEST_DIR%\!FNAME!"
    )
)

echo   Phase 1: Parsing %EVAL_TOTAL% files (batch mode)...
set "DOCPARSE_OUTPUT_DIR=%EVAL_TMPDIR%"
ailang run --batch --entry main --caps IO,FS,Env --max-recursion-depth 50000 %MAIN_AIL% %BATCH_FILES% >nul 2>&1

echo   Phase 2: Evaluating...
for %%g in ("%GOLDEN_DIR%\*.json") do (
    set "FNAME=%%~ng"
    set "OUTPUT_JSON=%EVAL_TMPDIR%\!FNAME!.json"
    if exist "!OUTPUT_JSON!" (
        for /f "delims=" %%r in ('ailang run --entry evalMain --caps IO,FS,Env docparse\services\eval.ail "%%g" "!OUTPUT_JSON!" 2^>^&1') do (
            echo %%r | findstr /c:"Score: 100" >nul && (
                echo     !FNAME!: 100%%
                set /a EVAL_PASS+=1
            ) || (
                echo     !FNAME!: FAIL
                set /a EVAL_FAIL+=1
            )
        )
    ) else (
        echo     !FNAME!: FAIL (not parsed)
        set /a EVAL_FAIL+=1
    )
)

rd /s /q "%EVAL_TMPDIR%" 2>nul
echo.
echo AILANG eval: %EVAL_PASS%/%EVAL_TOTAL% passed (%EVAL_FAIL% failures)
popd
exit /b 0

:expand_folder
:: Expand a folder into individual files
set "FOLDER=%~1"
for %%e in (%SUPPORTED_EXTS%) do (
    for %%f in ("%FOLDER%\*.%%e") do (
        if exist "%%f" (
            set /a FILE_COUNT+=1
            set "FILE_!FILE_COUNT!=%%~ff"
        )
    )
)
exit /b 0
