#set generator = $current_class.generator

extern JSClass  *js_${generator.prefix}_${current_class.class_name}_class;
extern JSObject *js_${generator.prefix}_${current_class.class_name}_prototype;

JSBool js_${generator.prefix}_${current_class.class_name}_constructor(JSContext *cx, uint32_t argc, jsval *vp);
void js_${generator.prefix}_${current_class.class_name}_finalize(JSContext *cx, JSObject *obj);
void js_register_${generator.prefix}_${current_class.class_name}(JSContext *cx, JSObject *global);
void register_all_${generator.prefix}();

