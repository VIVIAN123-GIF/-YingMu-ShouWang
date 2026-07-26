def replace_target_link(text: str) -> str:
    old_url = ""
    new_url = ""
    return text.replace(old_url, new_url)

if __name__ == "__main__":
    raw_content = """粘贴文档文本"""
    result = replace_target_link(raw_content)
    print(result)