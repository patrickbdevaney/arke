// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

/**
 * @title PredictionMarketOracle
 * @notice Arke's onchain accuracy oracle.
 * Records probability estimates and tracks resolution accuracy.
 * Deployed on Arc testnet as proof of autonomous agent operation.
 */
contract PredictionMarketOracle {

    struct Prediction {
        bytes32 conditionId;
        string question;
        uint8 marketPct;       // market consensus at time of prediction
        uint8 arkePct;         // Arke's estimate
        uint256 timestamp;
        bool resolved;
        bool outcome;          // true = YES resolved
        bool correct;          // true = Arke's direction matched outcome
    }

    address public owner;
    address public agent;      // authorized agent wallet (Circle)

    mapping(bytes32 => Prediction) public predictions;
    bytes32[] public predictionIds;

    uint256 public totalPredictions;
    uint256 public totalResolved;
    uint256 public totalCorrect;

    // Brier score numerator * 10000 for integer math
    uint256 public brierScoreNumeratorX10000;

    event PredictionLogged(
        bytes32 indexed conditionId,
        string question,
        uint8 marketPct,
        uint8 arkePct,
        int16 edge,
        uint256 timestamp
    );

    event PredictionResolved(
        bytes32 indexed conditionId,
        bool outcome,
        bool correct,
        uint8 arkePct
    );

    modifier onlyAuthorized() {
        require(
            msg.sender == owner || msg.sender == agent,
            "Not authorized"
        );
        _;
    }

    constructor(address _agent) {
        owner = msg.sender;
        agent = _agent;
    }

    function setAgent(address _agent) external {
        require(msg.sender == owner, "Only owner");
        agent = _agent;
    }

    function logPrediction(
        bytes32 conditionId,
        string calldata question,
        uint8 marketPct,
        uint8 arkePct
    ) external onlyAuthorized {
        require(!predictions[conditionId].resolved, "Already resolved");
        require(marketPct <= 100 && arkePct <= 100, "Invalid pct");

        predictions[conditionId] = Prediction({
            conditionId: conditionId,
            question: question,
            marketPct: marketPct,
            arkePct: arkePct,
            timestamp: block.timestamp,
            resolved: false,
            outcome: false,
            correct: false
        });

        predictionIds.push(conditionId);
        totalPredictions++;

        int16 edge = int16(uint16(arkePct)) - int16(uint16(marketPct));

        emit PredictionLogged(
            conditionId,
            question,
            marketPct,
            arkePct,
            edge,
            block.timestamp
        );
    }

    function resolvePrediction(
        bytes32 conditionId,
        bool outcome
    ) external onlyAuthorized {
        Prediction storage p = predictions[conditionId];
        require(p.timestamp > 0, "Prediction not found");
        require(!p.resolved, "Already resolved");

        p.resolved = true;
        p.outcome = outcome;

        // Correct if Arke's direction matched (or was closer to reality)
        bool arkeCorrect = outcome
            ? (p.arkePct >= p.marketPct)  // Arke was more bullish and it resolved YES
            : (p.arkePct <= p.marketPct); // Arke was more bearish and it resolved NO

        // Also correct if both agree and both wrong — track pure direction
        if (p.arkePct == p.marketPct) {
            arkeCorrect = false; // No edge, no credit
        }

        p.correct = arkeCorrect;
        totalResolved++;
        if (arkeCorrect) totalCorrect++;

        // Brier score: (forecast - outcome)^2, scaled by 10000
        // Lower is better. Perfect = 0, Random = 2500
        uint256 forecast = outcome ? p.arkePct : (100 - p.arkePct);
        uint256 error = forecast > 100 ? forecast - 100 : 100 - forecast;
        // Simplified: penalize distance from correct outcome
        uint256 brierContrib = (error * error);
        brierScoreNumeratorX10000 += brierContrib;

        emit PredictionResolved(conditionId, outcome, arkeCorrect, p.arkePct);
    }

    function getBrierScore() external view returns (uint256) {
        if (totalResolved == 0) return 0;
        return brierScoreNumeratorX10000 / totalResolved;
    }

    function getAccuracy() external view returns (uint256) {
        if (totalResolved == 0) return 0;
        return (totalCorrect * 100) / totalResolved;
    }

    function getPrediction(bytes32 conditionId)
        external view returns (Prediction memory)
    {
        return predictions[conditionId];
    }

    function getPredictionCount() external view returns (uint256) {
        return predictionIds.length;
    }
}
