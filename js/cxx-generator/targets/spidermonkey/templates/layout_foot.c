void register_all_${prefix}() {
	JSContext *cx = ScriptingCore::getInstance()->getGlobalContext();
	JSObject *obj = JS_GetGlobalObject(cx);
	#if $target_ns
	// first, try to get the ns
	jsval nsval;
	JSObject *ns;
	JS_GetProperty(cx, obj, "${target_ns}", &nsval);
	if (nsval == JSVAL_VOID) {
		ns = JS_NewObject(cx, NULL, NULL, NULL);
		nsval = OBJECT_TO_JSVAL(ns);
		JS_SetProperty(cx, obj, "${target_ns}", &nsval);
	} else {
		JS_ValueToObject(cx, nsval, &ns);
	}
	obj = ns;
	#end if

	#for jsclass in $sorted_classes
	js_register_${prefix}_${jsclass}(cx, obj);
	#end for
}

