## ===== static function implementation template - for overloaded functions
JSBool ${signature_name}(JSContext *cx, uint32_t argc, jsval *vp)
{
	jsval *argv = JS_ARGV(cx, vp);
	JSObject *obj;
	${namespaced_class_name}* cobj;
#if not $is_constructor
	obj = JS_THIS_OBJECT(cx, vp);
	cobj = (${namespaced_class_name} *)JS_GetPrivate(obj);
	if (!cobj) {
		return JS_FALSE;
	}
#end if

#for func in $implementations
	#set arg_list = ""
	#set arg_array = []
	#if $func.min_args >= 0
	if (argc == ${func.min_args}) {
		#set count = 0
		#for $arg in $func.arguments
		${arg.to_string($generator)} arg${count};
		${arg.to_native({"generator": $generator,
						 "in_value": "argv[" + str(count) + "]",
						 "out_value": "arg" + str(count),
						 "class_name": $class_name,
						 "level": 2,
						 "ntype": str($arg)})};
			#set $arg_array += ["arg"+str(count)]
			#set $count = $count + 1
		#end for
		#set $arg_list = ", ".join($arg_array)
	#end if
	#if $is_constructor
		cobj = new ${namespaced_class_name}(${arg_list});
		js_type_class_t *typeClass;
		const char* type = cobj->getObjectType();
		HASH_FIND_STR(_js_global_type_ht, type, typeClass);
		assert(typeClass);
		obj = JS_NewObject(cx, typeClass->jsclass, typeClass->proto, typeClass->parentProto);
		JS_SetPrivate(obj, cobj);
\#ifdef COCOS2D_JAVASCRIPT
		JS_AddObjectRoot(cx, &obj);
\#endif
	#else
		#if str($func.ret_type) != "void"
		${func.ret_type} ret = cobj->${func.func_name}($arg_list);
		jsval jsret; ${func.ret_type.from_native({"generator": $generator,
												  "in_value": "ret",
												  "out_value": "jsret",
												  "level": 2})};
		JS_SET_RVAL(cx, vp, jsret);
		#else
		cobj->${func.func_name}($arg_list);
		#end if
		return JS_TRUE;
	#end if
	}
#end for
#if $is_constructor
	if (cobj) {
		JS_SetPrivate(obj, cobj);
		JS_SET_RVAL(cx, vp, OBJECT_TO_JSVAL(obj));
		return JS_TRUE;
	}
#end if
	return JS_FALSE;
}
