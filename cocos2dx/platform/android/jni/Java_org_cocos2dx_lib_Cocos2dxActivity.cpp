#include <stdlib.h>
#include <jni.h>
#include <android/log.h>
#include <android/asset_manager.h>
#include <android/asset_manager_jni.h>
#include "JniHelper.h"

extern "C"
{

#define  LOG_TAG    "Java_org_cocos2dx_lib_Cocos2dxActivity.cpp"
#define  LOGD(...)  __android_log_print(ANDROID_LOG_DEBUG,LOG_TAG,__VA_ARGS__)

void Java_org_cocos2dx_lib_Cocos2dxActivity_nativeSetAssetManager(JNIEnv* env,
                                                                  jobject thiz,
                                                                  jobject java_assetmanager) {
    LOGD("nativeSetAssetManager");

    AAssetManager* assetmanager =
        AAssetManager_fromJava(env, java_assetmanager);
    if (NULL == assetmanager) {
        LOGD("assetmanager : is NULL");
        return;
    }

    cocos2d::JniHelper::setAssetManager(assetmanager);

    LOGD("... assetmanager set successfully.");
}

}
