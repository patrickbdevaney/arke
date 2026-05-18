// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

/**
 * @title PredictionMarketLog
 * @notice Arke's immutable audit trail on Arc testnet.
 * @dev Every market the agent identifies is logged here with probability estimate and tweet URL.
 *      This proves the agent has been operating continuously and transparently.
 */
contract PredictionMarketLog {
    struct MarketEntry {
        bytes32 conditionId;
        string  question;
        uint8   probabilityPct;
        uint256 loggedAt;
        string  tweetUrl;
        bool    resolved;
        bool    wasCorrect;
    }

    MarketEntry[] public entries;
    address public immutable owner;
    uint256 public totalCorrect;
    uint256 public totalResolved;

    event MarketLogged(
        uint256 indexed entryId,
        bytes32 indexed conditionId,
        uint8   probabilityPct,
        uint256 loggedAt
    );

    event MarketResolved(
        uint256 indexed entryId,
        bool    wasCorrect,
        uint256 resolvedAt
    );

    modifier onlyOwner() {
        require(msg.sender == owner, "Not owner");
        _;
    }

    constructor() {
        owner = msg.sender;
    }

    function logMarket(
        bytes32       conditionId,
        string calldata question,
        uint8         probabilityPct,
        string calldata tweetUrl
    ) external onlyOwner returns (uint256 entryId) {
        require(probabilityPct <= 100, "Invalid probability");
        entryId = entries.length;
        entries.push(MarketEntry({
            conditionId:    conditionId,
            question:       question,
            probabilityPct: probabilityPct,
            loggedAt:       block.timestamp,
            tweetUrl:       tweetUrl,
            resolved:       false,
            wasCorrect:     false
        }));
        emit MarketLogged(entryId, conditionId, probabilityPct, block.timestamp);
    }

    function resolveMarket(
        uint256 entryId,
        bool    wasCorrect
    ) external onlyOwner {
        require(entryId < entries.length, "Invalid entry");
        require(!entries[entryId].resolved, "Already resolved");
        entries[entryId].resolved   = true;
        entries[entryId].wasCorrect = wasCorrect;
        totalResolved++;
        if (wasCorrect) totalCorrect++;
        emit MarketResolved(entryId, wasCorrect, block.timestamp);
    }

    function totalEntries() external view returns (uint256) {
        return entries.length;
    }

    function accuracyBps() external view returns (uint256) {
        if (totalResolved == 0) return 0;
        return (totalCorrect * 10000) / totalResolved;
    }

    function getEntry(uint256 entryId) external view returns (MarketEntry memory) {
        require(entryId < entries.length, "Invalid entry");
        return entries[entryId];
    }
}
