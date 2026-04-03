import { DocParse } from '@ailang/parse';

const client = new DocParse({ apiKey: 'dp_your_key_here' });

const result = await client.parse('report.docx');
for (const block of result.blocks) {
  if (block.type === 'heading') console.log(`H${block.level}: ${block.text}`);
  if (block.type === 'table') console.log(`Table: ${block.rows?.length} rows`);
  if (block.type === 'change') console.log(`${block.changeType} by ${block.author}`);
}

// Unstructured migration — one import change:
import { UnstructuredClient } from '@ailang/parse';
const uc = new UnstructuredClient({ serverUrl: 'https://docparse.ailang.sunholo.com' });
const elements = await uc.general.partition({ file: 'report.docx' });