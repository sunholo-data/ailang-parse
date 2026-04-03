client := docparse.New("dp_your_key_here")

result, err := client.Parse(ctx, "report.docx")
for _, block := range result.Blocks {
    switch block.Type {
    case "heading":
        fmt.Printf("H%d: %s\n", block.Level, block.Text)
    case "table":
        fmt.Printf("Table: %d rows\n", len(block.Rows))
    case "change":
        fmt.Printf("%s by %s\n", block.ChangeType, block.Author)
    }
}

// Unstructured migration:
uc := docparse.NewUnstructuredClient("https://docparse.ailang.sunholo.com")
elements, _ := uc.Partition(ctx, "report.docx")