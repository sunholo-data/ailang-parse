# Parse an EML email file
ailang run --entry main --caps IO,FS,Env \
  ~/.ailang/cache/registry/sunholo/ailang_parse/*/docparse/main.ail inbox.eml

# Parse an MBOX archive (multiple messages)
ailang run --entry main --caps IO,FS,Env \
  ~/.ailang/cache/registry/sunholo/ailang_parse/*/docparse/main.ail archive.mbox