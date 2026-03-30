/**
 * Prism.js language definition for AILANG
 * Derived from the AILANG TextMate grammar (ailang.tmLanguage.json)
 * https://ailang.sunholo.com
 */
Prism.languages.ailang = {
  'comment': [
    { pattern: /--.*$/, greedy: true },
    { pattern: /\/\/.*$/, greedy: true }
  ],
  'string': {
    pattern: /"(?:[^"\\]|\\.)*"/,
    greedy: true,
    inside: {
      'interpolation': { pattern: /\$\{[^}]+\}/ }
    }
  },
  'char': {
    pattern: /'(?:[^'\\]|\\[nrt0'\\])'/,
    alias: 'string'
  },
  'keyword': [
    // Control flow
    { pattern: /\b(?:if|then|else|match|with)\b/ },
    // Binding
    { pattern: /\b(?:let|letrec|in|func|pure|export|import|module|extern|as)\b/ },
    // Type keywords
    { pattern: /\b(?:type|class|instance|forall|exists)\b/ },
    // Testing/contracts
    { pattern: /\b(?:test|tests|property|properties|assert|ensures|requires)\b/ },
    // Concurrency (future)
    { pattern: /\b(?:spawn|parallel|select|channel|send|recv|timeout)\b/ }
  ],
  'builtin': {
    pattern: /\b(?:print|println|show|intToFloat|floatToInt|decode|encode)\b/,
    alias: 'function'
  },
  'boolean': /\b(?:true|false)\b/,
  'effect': {
    pattern: /\b(?:IO|FS|Net|Clock|Env|Rand|Debug|AI)\b/,
    alias: 'class-name'
  },
  'type-primitive': {
    pattern: /\b(?:int|float|bool|string|char|unit)\b/,
    alias: 'builtin'
  },
  'class-name': [
    // Standard library types
    { pattern: /\b(?:Option|Result|List|Tuple|Array|Json|Some|None|Ok|Err|XmlNode)\b/ },
    // User-defined types (capitalized)
    { pattern: /\b[A-Z][a-zA-Z0-9]*\b/ }
  ],
  'function': {
    pattern: /\b(?=[a-z_])[a-z_][a-zA-Z0-9_]*(?=\s*[\(])/
  },
  'number': [
    { pattern: /\b0x[\da-fA-F]+\b/ },
    { pattern: /\b\d+\.\d+(?:[eE][+-]?\d+)?\b/ },
    { pattern: /\b\d+\b/ }
  ],
  'operator': [
    { pattern: /=>/ },
    { pattern: /->/ },
    { pattern: /<-/ },
    { pattern: /::/ },
    { pattern: /\+\+/ },
    { pattern: /[!=]=|<=?|>=?/ },
    { pattern: /&&|\|\|/ },
    { pattern: /\bnot\b/ },
    { pattern: /[+\-*/%]/ },
    { pattern: /!/ },
    { pattern: /\|/ }
  ],
  'punctuation': /[{}[\]();,.:]/
};

// Alias so language-ail also works
Prism.languages.ail = Prism.languages.ailang;
