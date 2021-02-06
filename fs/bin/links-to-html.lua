function Link(el)
  el.target = string.gsub(el.target, "README.md", "index.html")
  el.target = string.gsub(el.target, "%.md", ".html")
  return el
end
