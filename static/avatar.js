import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { VRMLoaderPlugin } from '@pixiv/three-vrm';

// =========================================================================
// 🎛️ チューニング用パラメータ集約エリア（ここを調整するだけで挙動が変わります）
// =========================================================================
const LIP_SYNC_CONFIG = {
    minVolume: 0.03,         // リップシンクが反応し始める最小音量閾値
    speedAA: 14,             // 「あ」の口の動く速さ（テンポ）
    speedEE: 11,             // 「い/え」の口の動く速さ
    speedOO: 8,              // 「う/お」の口の動く速さ

    // 通常時（neutral, sad, angry, surprised）の口の開き具合
    neutral: {
        maxOpen: 0.70,       // 口の最大開き幅（アゴ外れ防止のため0.85以下推奨）
        aaGain: 0.35,        // 「あ」のブレンド最大強度
        eeGain: 0.20,        // 「え」のブレンド最大強度
        ooGain: 0.15         // 「お」のブレンド最大強度
    },
    // 笑顔時（happy）の口の開き具合（ご指摘の「開きすぎ・バッティング違和感」の特化調整エリア）
    happy: {
        maxOpen: 0.25,       // 笑顔の原型を崩さないよう、口の開き幅を極小にロック
        aaGain: 0.10,        // 笑顔用「あ」の最大強度
        eeGain: 0.06,        // 笑顔用「え」の最大強度
        ooGain: 0.05         // 笑顔用「お」の最大強度
    }
};

const EXPRESSION_CONFIG = {
    happy:     { weightSpeaking: 1.0, keepEyes: true },  // 笑顔時は喋っていても「にっこり目」を1.0で完全固定
    sad:       { weightSpeaking: 0.6, keepEyes: false }, // 笑顔以外は、リップシンクを綺麗に見せるため
    angry:     { weightSpeaking: 0.6, keepEyes: false }, // 喋っている間だけ表情の重みをマイルドに減衰
    surprised: { weightSpeaking: 0.6, keepEyes: false }
};
// =========================================================================

// 他ファイルから参照するグローバルバインド
window.currentVrm = undefined;
window.isSpeaking = false;
window.currentVrmEmotionName = 'neutral';

const container = document.getElementById('canvas-container');
const scene = new THREE.Scene();

let width = container.clientWidth;
let height = container.clientHeight;

const camera = new THREE.PerspectiveCamera(28, width / height, 0.1, 20.0);
camera.position.set(0.0, 1.2, 3.0); 

const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
renderer.setSize(width, height);
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
container.appendChild(renderer.domElement);

// JARVIS リング装飾がキャンバスの上に表示されるよう z-index を設定
Object.assign(renderer.domElement.style, {
    position: 'absolute',
    top: '0', left: '0',
    zIndex: '4',
});

const ambientLight = new THREE.AmbientLight(0xffeedd, 1.0);
scene.add(ambientLight);
const directionalLight = new THREE.DirectionalLight(0xfffbea, 1.0);
directionalLight.position.set(1.0, 1.0, 1.0).normalize();
scene.add(directionalLight);

// 感情連動ポイントライト（アバター前方）
const emotionLight = new THREE.PointLight(0x00ffcc, 0.0, 4.0);
emotionLight.position.set(0.0, 1.2, 1.5);
scene.add(emotionLight);

const EMOTION_LIGHT_COLORS = {
    neutral:   0x00ffcc,
    happy:     0xffdd44,
    sad:       0x4499ff,
    angry:     0xff4433,
    surprised: 0xffffff,
};
let targetLightIntensity = 0.0;
let currentLightIntensity = 0.0;

const EMOTION_POSES = {
    neutral:   { armLz: 1.3,  armLx: 0.1,  armRz: -1.3,  armRx: 0.1,  shoulderZ: 0.0,  headX: 0.0 },
    happy:     { armLz: 0.8,  armLx: 0.4,  armRz: -0.8,  armRx: 0.4,  shoulderZ: -0.04, headX: -0.06 }, 
    sad:       { armLz: 1.45, armLx: 0.0,  armRz: -1.45, armRx: 0.0,  shoulderZ: 0.06,  headX: 0.18 },  
    angry:     { armLz: 1.15, armLx: -0.1, armRz: -1.15, armRx: -0.1, shoulderZ: -0.08, headX: 0.06 },  
    surprised: { armLz: 0.4,  armLx: 0.6,  armRz: -0.4,  armRx: 0.6,  shoulderZ: -0.05, headX: -0.12 }  
};

let currentPose = { ...EMOTION_POSES.neutral };
let targetPose  = { ...EMOTION_POSES.neutral };

window.playMotion = (emotion) => {
    if (EMOTION_POSES[emotion]) {
        targetPose = EMOTION_POSES[emotion];
        window.currentVrmEmotionName = emotion;

        if (window.currentVrm && window.currentVrm.expressionManager) {
            const expressionNames = ['happy', 'sad', 'angry', 'surprised'];
            if (emotion === 'neutral') {
                expressionNames.forEach(exp => window.currentVrm.expressionManager.setValue(exp, 0));
            } else if (expressionNames.includes(emotion)) {
                window.currentVrm.expressionManager.setValue(emotion, 1.0);
            }
        }

        // 感情連動ライト色の更新
        const col = EMOTION_LIGHT_COLORS[emotion] ?? EMOTION_LIGHT_COLORS.neutral;
        emotionLight.color.setHex(col);
        targetLightIntensity = emotion === 'neutral' ? 0.0 : 0.55;
    }
};

const loader = new GLTFLoader();
loader.register((parser) => new VRMLoaderPlugin(parser));
const vrmPath = './7151938431140058353.vrm'; 

loader.load(vrmPath, (gltf) => {
    const vrm = gltf.userData.vrm;
    scene.add(vrm.scene);
    window.currentVrm = vrm;
    vrm.scene.rotation.y = Math.PI; 
    vrm.scene.position.x = 0.0; 
    vrm.scene.scale.set(1.18, 1.18, 1.18); 
    vrm.scene.position.y = -0.15; 
    document.getElementById('system-status').innerText = "システム起動準備完了（スペースキーで起動）";
});

const clock = new THREE.Clock();
let blinkTimer = 0;
let nextBlinkTime = 3.0; 

function animate() {
    requestAnimationFrame(animate);
    const deltaTime = clock.getDelta();
    const elapsedTime = clock.getElapsedTime();
    const t = elapsedTime; 
    
    if (window.currentVrm) {
        const vrm = window.currentVrm;
        const expressionManager = vrm.expressionManager;
        const humanoid = vrm.humanoid;

        // ボーン・表情補間（Lerp）
        const lerpFactor = 0.08; 
        currentPose.armLz += (targetPose.armLz - currentPose.armLz) * lerpFactor;
        currentPose.armLx += (targetPose.armLx - currentPose.armLx) * lerpFactor;
        currentPose.armRz += (targetPose.armRz - currentPose.armRz) * lerpFactor;
        currentPose.armRx += (targetPose.armRx - currentPose.armRx) * lerpFactor;
        currentPose.shoulderZ += (targetPose.shoulderZ - currentPose.shoulderZ) * lerpFactor;
        currentPose.headX += (targetPose.headX - currentPose.headX) * lerpFactor;

        // 集約パラメータを反映した感情表情の動的適用
        if (expressionManager) {
            const currentEmotion = window.currentVrmEmotionName;
            if (currentEmotion !== 'neutral' && EXPRESSION_CONFIG[currentEmotion]) {
                const config = EXPRESSION_CONFIG[currentEmotion];
                if (window.isSpeaking && !config.keepEyes) {
                    expressionManager.setValue(currentEmotion, config.weightSpeaking);
                } else {
                    expressionManager.setValue(currentEmotion, 1.0); // 笑顔時は目を維持するため1.0固定
                }
            }
        }

        // 音量エネルギーのサンプリング
        let currentVolume = 0;
        if (window.isSpeaking && window.audioAnalyser) {
            const array = new Uint8Array(window.audioAnalyser.frequencyBinCount);
            window.audioAnalyser.getByteTimeDomainData(array);
            let maxAmp = 0;
            for (let i = 0; i < array.length; i++) {
                const val = Math.abs(array[i] - 128);
                if (val > maxAmp) maxAmp = val;
            }
            currentVolume = maxAmp / 128.0;
        }

        // ボーンノード適用
        const spine = humanoid.getNormalizedBoneNode('spine');
        const head = humanoid.getNormalizedBoneNode('head');
        const leftShoulder = humanoid.getNormalizedBoneNode('leftShoulder');
        const rightShoulder = humanoid.getNormalizedBoneNode('rightShoulder');
        const leftUpperArm = humanoid.getNormalizedBoneNode('leftUpperArm');
        const rightUpperArm = humanoid.getNormalizedBoneNode('rightUpperArm');
        const leftLowerArm = humanoid.getNormalizedBoneNode('leftLowerArm');
        const rightLowerArm = humanoid.getNormalizedBoneNode('rightLowerArm');

        if (spine) spine.rotation.x = Math.sin(t * 2.5) * 0.01 + 0.01;
        if (head) {
            head.rotation.y = Math.sin(t * 0.5) * 0.02;
            head.rotation.x = currentPose.headX;
        }
        if (leftShoulder) leftShoulder.rotation.z = currentPose.shoulderZ;
        if (rightShoulder) rightShoulder.rotation.z = -currentPose.shoulderZ;

        if (leftUpperArm) {
            leftUpperArm.rotation.z = currentPose.armLz + Math.sin(t * 1.5) * 0.02 + Math.cos(t * 0.7) * 0.01;
            leftUpperArm.rotation.x = currentPose.armLx + Math.sin(t * 0.9) * 0.015;
        }
        if (rightUpperArm) {
            rightUpperArm.rotation.z = currentPose.armRz + Math.sin(t * 1.6) * 0.02 + Math.cos(t * 0.8) * 0.01;
            rightUpperArm.rotation.x = currentPose.armRx + Math.sin(t * 1.0) * 0.015;
        }
        if (leftLowerArm) leftLowerArm.rotation.y = -1.0 + Math.cos(t * 1.3) * 0.03 + Math.sin(t * 0.6) * 0.015;
        if (rightLowerArm) rightLowerArm.rotation.y = 1.0 + Math.cos(t * 1.4) * 0.03 + Math.sin(t * 0.5) * 0.015;

        const baseY = parseFloat(document.getElementById('param-vrm-y').value);
        vrm.scene.position.y = baseY + Math.sin(t * 2.5) * 0.005;

        // 自動瞬き（笑顔で発話中は干渉防止のためスキップ）
        blinkTimer += deltaTime;
        const isHappySpeaking = window.isSpeaking && window.currentVrmEmotionName === 'happy';
        if (blinkTimer >= nextBlinkTime && !isHappySpeaking) {
            const blinkDuration = 0.2;
            const progress = blinkTimer - nextBlinkTime;
            if (progress < blinkDuration) {
                const blinkVal = Math.sin((progress / blinkDuration) * Math.PI);
                expressionManager.setValue('blink', blinkVal);
            } else {
                expressionManager.setValue('blink', 0);
                blinkTimer = 0;
                nextBlinkTime = 2.0 + Math.random() * 4.0;
            }
        }

        // 集約パラメータを反映したインテリジェント・リップシンク
        if (window.isSpeaking && window.audioAnalyser && expressionManager) {
            if (currentVolume > LIP_SYNC_CONFIG.minVolume) {
                // 現在の感情状態に応じて、適用するパラメータセットを動的に切り替える
                const poseMode = (window.currentVrmEmotionName === 'happy') ? LIP_SYNC_CONFIG.happy : LIP_SYNC_CONFIG.neutral;
                
                const openScale = Math.min(currentVolume * 2.3, poseMode.maxOpen);
                const aaBlend = (Math.sin(t * LIP_SYNC_CONFIG.speedAA) + 1.0) * poseMode.aaGain * openScale;
                const eeBlend = (Math.cos(t * LIP_SYNC_CONFIG.speedEE) + 1.0) * poseMode.eeGain * openScale;
                const ooBlend = (Math.sin(t * LIP_SYNC_CONFIG.speedOO) + 1.0) * poseMode.ooGain * openScale;
                
                expressionManager.setValue('aa', aaBlend);
                expressionManager.setValue('ee', eeBlend);
                expressionManager.setValue('oo', ooBlend);
                ['ih', 'uu'].forEach(v => expressionManager.setValue(v, 0));
            } else {
                ['aa', 'ih', 'uu', 'ee', 'oo'].forEach(v => expressionManager.setValue(v, 0));
            }
        } else if (expressionManager) {
            ['aa', 'ih', 'uu', 'ee', 'oo'].forEach(v => expressionManager.setValue(v, 0));
        }

        // 感情ライト強度を滑らかに補間
        currentLightIntensity += (targetLightIntensity - currentLightIntensity) * 0.05;
        emotionLight.intensity = currentLightIntensity;

        vrm.update(deltaTime);
    }
    renderer.render(scene, camera);
}
animate();

window.addEventListener('resize', () => {
    width = container.clientWidth;
    height = container.clientHeight;
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    renderer.setSize(width, height);
});