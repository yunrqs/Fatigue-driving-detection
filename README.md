# 基于眨眼与情绪的走神预测复现

本项目复现论文 **Detecting Attention and Two Different Mind Wandering States Using
Blink Frequency and Emotion Analysis** 的特征与经典机器学习流程。当前使用可直接公开下载的
MWDET 数据训练 `focused / not_focused` 二分类器，并保留 PAFE 视频入口及未来
`focused / deliberate_mw / spontaneous_mw` 三分类接口。

> MWDET 包含真实走神探针与 WebGazer/Tobii 眼动数据，但不包含原始人脸视频。因此当前
> 真实模型使用眼动特征，不会伪造情绪特征。PAFE 视频仍需向原作者申请。

## 1. 项目结构

```text
.
├── web-react/                       # React + TypeScript 前端
│   ├── src/
│   │   ├── pages/Monitor/           # 监测页面和交互流程
│   │   ├── features/monitoring/     # 请求、摄像头、类型、业务组件
│   │   ├── features/gaze/           # 浏览器内视线预测
│   │   │   ├── components/         # 面板、校准验证、落点标记
│   │   │   ├── hooks/              # 状态与生命周期
│   │   │   ├── services/           # 模型加载、推理调度与释放
│   │   │   ├── core/               # 特征、回归算法及来源许可证
│   │   │   └── types.ts
│   │   ├── components/             # 通用图标
│   │   ├── styles/                 # 全局样式
│   │   ├── App.tsx
│   │   └── main.tsx
│   ├── tests/e2e/                  # Playwright 浏览器测试
│   ├── tests/unit/                 # 视线回归算法测试
│   ├── public/mediapipe/face_mesh/  # 浏览器模型与 WASM 资源
│   └── package.json                # Vite / TypeScript 构建配置同级
├── backend/
│   ├── src/
│   │   ├── config/paths.py          # 统一资源路径
│   │   ├── modules/monitoring/      # routes.py 接口、service.py 会话
│   │   ├── algorithms/
│   │   │   ├── emotion/            # 情绪模型训练与推理
│   │   │   └── blink_detection/    # EAR 和眨眼检测
│   │   ├── mind_wandering/         # 离线数据、特征、训练、推理及测试
│   │   ├── routes/index.py         # API 路由注册
│   │   ├── app.py                  # 生命周期与静态页面托管
│   │   └── server.py               # 服务入口
│   ├── models/emotion/             # 情绪权重（dlib 关键点模型缺失时自动下载）
│   ├── outputs/                    # 实验结果、模型和训练图
│   ├── tests/unit/                 # 眨眼单元测试
│   ├── tests/integration/          # HTTP 契约测试
│   ├── requirements.txt            # 在线识别依赖
│   └── requirements-dev.txt        # 接口测试依赖
├── data/
│   ├── raw/                        # fer2013、mwdet、eegmeditation
│   └── processed/                  # 特征 CSV
├── docs/                           # 架构、接口、开发、部署说明
│   ├── papers/                     # 论文
│   └── specifications/             # 眨眼与视线模块规格说明
├── .gitignore
└── README.md
```

在线监测和离线训练共享算法，网页仍未接入 MWDET 走神分类器。
视线预测由 `features/gaze` 在浏览器内独立运行，与情绪/眨眼功能共用摄像头；
其模型资源随前端构建发布。使用方式见 [视线预测说明](docs/specifications/gaze-prediction.md)。
详见 [架构说明](docs/architecture.md)。

## 驾驶视频注视点叠加与分心预测（EyeCue + GazeFollower）

仓库另含独立的驾驶视频演示：[driver-gaze-demo](driver-gaze-demo/README.md)。
它使用 GazeFollower 进行摄像头注视点估计与校准，并将 EyeCue 分心概率叠加到播放的驾驶视频上。
这与本仓库现有的浏览器视线面板和 MWDET 眨眼/情绪分类流程相互独立。

EyeCue 最佳模型 checkpoint（约 1.66 GB）已公开托管在
[Hugging Face 模型仓库](https://huggingface.co/Thorfinn11111/eyecue_best_model)，
不包含在 GitHub 中。克隆仓库后，在 PowerShell 中从仓库根目录下载：

```powershell
New-Item -ItemType Directory -Force .\driver-gaze-demo\EyeCue\checkpoints | Out-Null
curl.exe -L --fail --retry 5 --output .\driver-gaze-demo\EyeCue\checkpoints\best_model.pth "https://huggingface.co/Thorfinn11111/eyecue_best_model/resolve/main/best_model.pth"
Get-Item .\driver-gaze-demo\EyeCue\checkpoints\best_model.pth | Select-Object Name,Length
```

完整安装、摄像头校准和驾驶视频预测步骤见演示目录的
[README](driver-gaze-demo/README.md)。

## 2. 方法与论文对应关系

每个注意力探针对应探针前一个时间窗口，默认长度为 5 秒。系统从窗口中提取：

- EAR 均值、标准差、四分位数、中位数和 MAD；
- 眨眼次数及每分钟眨眼频率；
- angry、disgust、fear、happy、sad、surprise、neutral 概率统计；
- 正面、负面和中性效价；
- 人脸有效帧比例，用于发现遮挡或检测失败。

训练脚本比较 Random Forest、Decision Tree、Gradient Boosting、SVM、KNN、
Logistic Regression 和 Gaussian Naive Bayes。验证使用 `subject_id` 分组，确保同一人的
片段不会同时出现在训练折和验证折中。主要比较 balanced accuracy、macro-F1、
weighted-F1、逐类指标和混淆矩阵。

论文报告的 99% accuracy 不能直接视为本项目预期结果。PAFE 的任务、参与者和标签定义
不同，而且走神类别不平衡；按受试者分组的结果通常也会低于随机按片段切分的结果。

## 3. 环境安装

### Windows 一键安装与启动

其他电脑先安装 **64 位 Python 3.10+（建议 3.11，勾选 Add Python to PATH）** 和
**Node.js 20.19+ 或 22.12+（包含 npm）**，然后完整解压项目。

1. 双击根目录 `setup.cmd`，自动创建隔离环境 `backend/.venv` 并安装后端、前端依赖。
2. 安装成功后双击 `start.cmd`，浏览器会自动打开 http://127.0.0.1:5173 。
3. 也可以直接双击 `start.cmd`：首次启动会自动执行上述安装，后续复用环境。

首次安装需要联网，PyTorch 等依赖较大，请等待安装完成。脚本不会自动安装 Python 或 Node.js；
缺少它们时会提示。运行期间保持启动窗口打开，正常退出可按 `Ctrl+C`。
依赖清单变化时会重新安装；安装失败后可直接重试。需要重新执行依赖安装时运行 `setup.cmd -Reinstall`。

**分发时必须包含 `backend/models/emotion/fer2013_best_model.pth` 和整个
`web-react/public/mediapipe/` 目录。** 模型权重被 `.gitignore` 排除，通过 Git 下载源码时需另行提供。
不要打包或复制 `.venv`、`node_modules`，它们由脚本在目标电脑生成。

`backend/models/dlib/shape_predictor_68_face_landmarks.dat`（dlib 68 点关键点，约 95 MB）
同样不在版本库中，无需手动准备：`setup.cmd` 会提前下载，点“开始识别”时若仍缺失也会自动补全并解压。
离线环境可自行下载后放入该路径，或用环境变量 `FOCUSLENS_FACE_PREDICTOR` 指向已有副本
（见 `backend/src/config/model_assets.py`）。
首次开启识别时，较新的 MediaPipe 还可能联网下载 Face Landmarker 模型。

上半身肢体动作（OpenPose `body_pose_model.pth`，约 200 MB）属于可选增强，官方只提供网盘下载，
脚本不会自动获取；该文件缺失时疲劳检测自动降级为“打哈欠 + 头部姿态”，眨眼、情绪与专注融合不受影响。
一键安装面向网页监测；离线训练、开发测试的额外依赖见下面的开发文档。

参见 [开发与测试](docs/development.md)，前端依赖在 web-react，后端依赖在 backend。
所有 Python 包入口从项目根目录运行。

## 4. 摄像头监测界面

唯一前端为 React + TypeScript，后端为 FastAPI。旧 web 目录已删除。
启动后端：`python -m backend.src.server`；启动前端：`npm --prefix web-react run dev`。
访问 http://127.0.0.1:5173 。先构建前端也可直接由 8001 端口的 FastAPI 托管。
安装、现有虚拟环境复用与测试见 [开发文档](docs/development.md)，构建托管见 [部署文档](docs/deployment.md)。

新增独立「视线预测」面板：开启摄像头后可单独启动，完成 16 点校准及 5 点
误差验证后显示网页区域内的注视落点。与情绪/眨眼分析共用摄像头，不控制鼠标。
使用方法、坐标定义及部署说明见 [视线预测说明](docs/specifications/gaze-prediction.md)。

## 5. MWDET：可直接复现的真实数据实验

MWDET 来源于 Zhao、Lofi 和 Hauff 2017 年的实验：13 名参与者分别观看两段 MOOC 视频，
系统每隔 30–60 秒响铃；如果参与者在过去 30 秒发生走神，就在响铃后按键，否则继续观看。
公开数据包含 200 个探针区间，其中 58 个走神、142 个专注。

### 5.1 下载

```powershell
python -m backend.src.mind_wandering.dataset.download_mwdet --output-dir data\raw\mwdet
```

下载器使用 GitHub 官方文件并校验 SHA-256：
`b12aa3f0b64e76c3fad5cbc3ad8c8ed469f97096121eb6b18397949d6b018e64`。

### 5.2 生成 WebGazer 特征

```powershell
python -m backend.src.mind_wandering.dataset.prepare_mwdet `
  --root data\raw\mwdet\Data_Publish\Data_Publish `
  --output data\processed\mwdet_webgazer_features.csv
```

每个样本使用相邻两次响铃之间的眼动数据，与原论文一致。特征包括 gaze X/Y 分布、眼动轨迹
长度、相邻采样点位移、注视次数与时长、扫视次数与角度、有效采样率等。阶段、探针序号和
视频时间只作为审计信息保存，训练时自动排除，防止时间位置泄漏。

### 5.3 留一受试者训练

```powershell
python -m backend.src.mind_wandering.training.train `
  --features data\processed\mwdet_webgazer_features.csv `
  --output-dir backend\outputs\mwdet_webgazer_lopo `
  --task binary `
  --folds 13 `
  --seed 42
```

13 折对应 leave-one-participant-out：每折完整留出一名参与者。这比随机按样本切分更能反映
模型面对新用户时的泛化能力。

### 5.4 当前复现结果

在排除阶段、探针序号和视频时间等元数据后，本仓库当前运行结果如下：

| 模型 | Balanced accuracy | Macro-F1 | 走神 Precision | 走神 Recall | 走神 F1 |
| --- | ---: | ---: | ---: | ---: | ---: |
| SVM | 0.548 | **0.540** | 0.342 | 0.448 | 0.388 |
| Naive Bayes | 0.508 | 0.410 | 0.295 | **0.741** | **0.422** |
| Gradient Boosting | 0.521 | 0.517 | 0.333 | 0.224 | 0.268 |
| KNN | 0.533 | 0.527 | 0.375 | 0.207 | 0.267 |
| Random Forest | 0.538 | 0.504 | 0.600 | 0.103 | 0.176 |

程序按 macro-F1 选择并保存 SVM，因为它在两个类别间更均衡；如果应用更重视“不漏掉走神”，
可以使用 Naive Bayes，但需要接受更多误报。完整七模型指标保存在
`backend/outputs/mwdet_webgazer_lopo/metrics.json`，折外预测保存在同目录的
`cross_validated_predictions.csv`。原 MWDET 项目报告 WebGazer + Naive Bayes 的走神 F1
约为 0.405；本实现的 0.422 与其处于相近范围，但特征实现和模型选择协议并非完全相同。

## 6. PAFE 数据申请与清单

PAFE 论文为：T. Lee et al., *Predicting Mind-Wandering With Facial Videos in Online
Lectures*, CVPR Workshops 2022。建议使用学校邮箱联系 `taekyung@kaist.ac.kr`，说明研究
用途并申请以下内容：

- 640p、30 FPS facial videos；
- probe timestamps；
- Focused / Not-Focused / Skip labels；
- subject IDs；
- 数据许可和引用要求。

不要把原始人脸视频提交到 Git，也不要向第三方分发。

获得数据后，参照 `backend/src/mind_wandering/dataset/manifest.example.csv` 建立原始清单：

```csv
subject_id,video_path,probe_time_sec,label
P001,data/raw/pafe/P001/session.mp4,40,focused
P001,data/raw/pafe/P001/session.mp4,80,not_focused
```

标准化并检查视频路径：

```powershell
python -m backend.src.mind_wandering.dataset.prepare_manifest `
  --input data\raw\pafe_annotations.csv `
  --output data\processed\manifest.csv `
  --task binary
```

视频尚未到位时，可只验证 CSV 格式：

```powershell
python -m backend.src.mind_wandering.dataset.prepare_manifest `
  --input backend\src\mind_wandering\dataset\manifest.example.csv `
  --output data\processed\manifest.example.normalized.csv `
  --task binary `
  --no-check-files
```

## 7. PAFE 视频特征提取

```powershell
python -m backend.src.mind_wandering.features.extract_features `
  --manifest data\processed\manifest.csv `
  --output data\processed\features.csv `
  --window-sec 5 `
  --sample-fps 10
```

`--sample-fps 10` 用于降低情绪网络推理开销；眨眼检测对采样率敏感。如果设备性能允许且
需要更接近原始 30 FPS，应改成 `--sample-fps 30`。不同采样率的结果不能直接混合训练。

默认情绪权重为 `backend/models/emotion/fer2013_best_model.pth`，也可通过 `--emotion-model` 指定。

## 8. 通用训练与评估

```powershell
python -m backend.src.mind_wandering.training.train `
  --features data\processed\features.csv `
  --output-dir backend\outputs\pafe_binary `
  --task binary `
  --folds 5 `
  --seed 42
```

输出包括：

```text
backend/outputs/pafe_binary/
├── mind_wandering_model.joblib       # 在全部数据上重训的最佳模型
├── metrics.json                      # 各模型分组交叉验证指标
└── cross_validated_predictions.csv  # 每个探针的折外预测
```

训练要求至少两个不同 `subject_id`。如果受试者少于五人，程序会自动把折数降低到受试者数。

## 9. 批量推理

对已经提取的特征进行预测：

```powershell
python -m backend.src.mind_wandering.inference.predict_features `
  --model backend\outputs\pafe_binary\mind_wandering_model.joblib `
  --features data\processed\features.csv `
  --output backend\outputs\predictions.csv
```

输出包含 `predicted_label`、`predicted_target`，以及模型支持时的各类别概率。

## 10. 三分类扩展

将来获得带 intentionality 的数据后，清单标签写为：

```text
focused
deliberate_mw
spontaneous_mw
```

然后在清单准备和训练命令中使用 `--task three_class`。特征列、受试者分组验证和推理文件
无需修改。PAFE 的 `not_focused` 不能自动拆成两个真实类别；项目不会用情绪或规则生成的
伪标签冒充主动/无意走神真值。

## 11. 测试

从项目根目录执行（使用已安装依赖的 Python 环境）：

```powershell
npm --prefix web-react run build
python -m unittest discover -s backend/tests -v
python -m unittest discover -s backend/src/mind_wandering/tests -v
npm --prefix web-react run test:unit
npm --prefix web-react run test:e2e
```

接口测试不加载大型模型；浏览器测试使用虚拟摄像头和模拟响应。

## 12. 已知限制

- PAFE 只提供专注/非专注真值，本阶段不是论文三分类的完全复现。
- MWDET 没有人脸视频，真实数据实验不能使用 FER 情绪模块或 EAR 眨眼模块。
- MWDET 的 WebGazer 数据约为 5 Hz，样本仅来自 13 名计算机背景参与者，泛化能力有限。
- FER-2013 在真实网课光照、姿态和人群上的领域偏移可能降低情绪特征质量。
- 面部行为只能提供走神概率，不能证明一个人的主观心理状态。
- 眼镜、遮挡、摄像头帧率、光线和人脸检测失败会影响 EAR 与眨眼率。
- 模型不能用于考试监控、惩罚或高风险人员评估。
- 发布实验结果时必须报告数据划分方式、类别分布和每类指标，不能只报告 accuracy。

## 13. 参考资料

- Mamun et al., *Detecting Attention and Two Different Mind Wandering States Using
  Blink Frequency and Emotion Analysis*, IEICE Transactions, 2026.
- Lee et al., [Predicting Mind-Wandering With Facial Videos in Online Lectures](https://openaccess.thecvf.com/content/CVPR2022W/CVPM/html/Lee_Predicting_Mind-Wandering_With_Facial_Videos_in_Online_Lectures_CVPRW_2022_paper.html), CVPRW 2022.
- Zhao, Lofi and Hauff, [Scalable Mind-Wandering Detection for MOOCs: A Webcam-Based Approach](https://github.com/Yue-ZHAO/MWDET_Project), EC-TEL 2017.
- Goodfellow et al., FER-2013.
- Soukupova and Cech, *Real-Time Eye Blink Detection using Facial Landmarks*, 2016.

## 14. 本次架构重构

保留 web-react 作为唯一前端并删除旧 web；将 FastAPI 独立到 backend，按路由、会话服务和配置分层；情绪、眨眼算法与 mind_wandering 统一移入 backend/src，权重和实验产物分别移入 backend/models、backend/outputs，FER-2013 数据移入 data/raw/fer2013。同步调整包导入、资源路径、测试位置及启动文档，保持核心识别算法、训练流程、API 协议和页面交互行为不变。

新增视线预测功能按前端业务模块纳入 `web-react/src/features/gaze`，内部划分 components、hooks、services、core 和业务类型；模型及 WASM 保留在 public/mediapipe/face_mesh，回归算法测试移入 tests/unit 并提供 test:unit 命令。此次整理仅调整文件位置、导入路径和文档，保持预测、校准、滤波及摄像头共享行为不变。
