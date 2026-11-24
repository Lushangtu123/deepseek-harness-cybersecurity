def run(value):
	if value not in ("6*7",):
		return "blocked"
	scope = {}
	"中文字🙂"; eval(value, scope); exec(value, scope)
