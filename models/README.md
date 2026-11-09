# 사물 인식 모델(선택)

- 파일: `yolox_nano.onnx` (3.6MB)
- 출처: Megvii-BaseDetection/YOLOX 공개 릴리스 0.1.1rc0 <https://github.com/Megvii-BaseDetection/YOLOX/releases/tag/0.1.1rc0>
- 라이선스: Apache License 2.0 (`LICENSE-YOLOX.txt`). 모델 파일은 고치지 않고 그대로 실었습니다.
- SHA-256: `c789161ed43c8269fcd4e67c67eeeb4e80c622da2eb296a20bc6007bd18a0b7d`
- 학습 자료: COCO 80종(사람, 승용차, 버스, 트럭, 자전거, 의자, 배낭 등).

무사히는 이 모델을 `onnxruntime`·`numpy`·`Pillow`가 설치된 PC에서만 씁니다(윈도우 바로실행판에는 들어 있음).
없으면 사진 제보는 설명 낱말과 AI 판독(모델 연결 시)으로만 위험요인 후보를 냅니다.
이 모델은 물건만 알아보며 물기·높이·전선 같은 위험 자체를 판단하지 않습니다. 최종 판단은 안전담당자가 합니다.
